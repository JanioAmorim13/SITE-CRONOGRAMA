import json
import os
import html
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import parse_qs

MINI_FLASK = False
try:  # pragma: no cover - caminho principal quando Flask está instalado.
    from flask import Flask, render_template_string, request, redirect, url_for, Response
except ModuleNotFoundError:  # pragma: no cover - fallback simples para ambientes off-line.
    MINI_FLASK = True
    from wsgiref.simple_server import make_server

    _HTTP_STATUS = {
        200: "OK",
        302: "FOUND",
        404: "NOT FOUND",
        405: "METHOD NOT ALLOWED",
    }

    class _RequestState(threading.local):
        current = None

    _request_state = _RequestState()

    class _RequestProxy:
        def __getattr__(self, name):
            if _request_state.current is None:
                raise RuntimeError("Nenhuma requisição ativa.")
            return getattr(_request_state.current, name)

    class _SimpleRequest:
        __slots__ = ("method", "path", "args", "form")

        def __init__(self, method: str, path: str, args: Dict[str, str], form: Dict[str, str]):
            self.method = method
            self.path = path
            self.args = args
            self.form = form

        def get_data(self, as_text: bool = False) -> str:
            return ""

    request = _RequestProxy()

    def render_template_string(template: str, **context: str) -> str:
        def _replace(match: re.Match) -> str:
            key = match.group(1).strip()
            if "|" in key:
                key = key.split("|", 1)[0].strip()
            return str(context.get(key, ""))

        return re.sub(r"{{\s*(.*?)\s*}}", _replace, template)

    class Response:
        def __init__(self, body="", status: int = 200, headers=None, mimetype: str = "text/html"):
            if isinstance(body, str):
                body_bytes = body.encode("utf-8")
            else:
                body_bytes = body
            self.body = body_bytes
            self.status = status
            self.headers = list(headers) if headers else []
            if mimetype:
                has_ct = any(h[0].lower() == "content-type" for h in self.headers)
                if not has_ct:
                    self.headers.append(("Content-Type", mimetype))

    def redirect(location: str) -> Response:
        resp = Response("", status=302)
        resp.headers.append(("Location", location))
        return resp

    class _Route:
        def __init__(self, rule: str, methods: Optional[List[str]], func):
            self.rule = rule
            self.methods = [m.upper() for m in (methods or ["GET"])]
            self.func = func
            self.pattern, self.params, self.segments = self._compile_rule(rule)

        @staticmethod
        def _compile_rule(rule: str):
            pattern = "^"
            params = []
            segments = []
            i = 0
            while i < len(rule):
                if rule[i] == "<":
                    j = rule.find(">", i)
                    if j == -1:
                        raise ValueError("Regra inválida")
                    inside = rule[i + 1 : j]
                    converter = str
                    name = inside
                    if inside.startswith("int:"):
                        converter = int
                        name = inside[4:]
                    regex = r"(?P<%s>\\d+)" % name if converter is int else r"(?P<%s>[^/]+)" % name
                    params.append((name, converter))
                    segments.append(("param", name))
                    pattern += regex
                    i = j + 1
                else:
                    literal_end = rule.find("<", i)
                    if literal_end == -1:
                        literal_end = len(rule)
                    literal = rule[i:literal_end]
                    pattern += re.escape(literal)
                    segments.append(("text", literal))
                    i = literal_end
            pattern += "$"
            return re.compile(pattern), params, segments

        def match(self, path: str):
            match = self.pattern.match(path)
            if not match:
                return None
            kwargs = {}
            for name, converter in self.params:
                value = match.group(name)
                kwargs[name] = converter(value)
            return kwargs

        def build_url(self, values: Dict[str, str]) -> str:
            parts = []
            for kind, value in self.segments:
                if kind == "text":
                    parts.append(value)
                else:
                    if value not in values:
                        raise ValueError(f"Parâmetro '{value}' ausente para URL")
                    parts.append(str(values[value]))
            return "".join(parts)

    _CURRENT_APP = None

    class Flask:
        def __init__(self, import_name: str):
            self.import_name = import_name
            self.debug = False
            self._routes: List[_Route] = []
            self._endpoints: Dict[str, _Route] = {}
            global _CURRENT_APP
            _CURRENT_APP = self

        def route(self, rule: str, methods: Optional[List[str]] = None):
            def decorator(func):
                route = _Route(rule, methods, func)
                endpoint = func.__name__
                route.endpoint = endpoint
                self._routes.append(route)
                self._endpoints[endpoint] = route
                return func

            return decorator

        def _dispatch(self, environ, start_response):
            path = environ.get("PATH_INFO", "") or "/"
            method = environ.get("REQUEST_METHOD", "GET").upper()
            matched_methods = []
            for route in self._routes:
                kwargs = route.match(path)
                if kwargs is None:
                    continue
                if method not in route.methods:
                    matched_methods.extend(route.methods)
                    continue
                qs = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
                args = {k: v[0] for k, v in qs.items()}
                form_data: Dict[str, str] = {}
                if method == "POST":
                    try:
                        length = int(environ.get("CONTENT_LENGTH") or 0)
                    except ValueError:
                        length = 0
                    body = environ["wsgi.input"].read(length) if length > 0 else b""
                    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                    form_data = {k: v[0] for k, v in parsed.items()}
                _request_state.current = _SimpleRequest(method, path, args, form_data)
                try:
                    result = route.func(**kwargs)
                finally:
                    _request_state.current = None
                if isinstance(result, Response):
                    response = result
                else:
                    response = Response(result)
                status_line = f"{response.status} {_HTTP_STATUS.get(response.status, 'OK')}"
                start_response(status_line, response.headers)
                return [response.body]
            if matched_methods:
                allow = ", ".join(sorted(set(matched_methods)))
                start_response(f"405 {_HTTP_STATUS[405]}", [("Allow", allow)])
                return [b"Method Not Allowed"]
            start_response(f"404 {_HTTP_STATUS[404]}", [("Content-Type", "text/plain")])
            return [b"Not Found"]

        def wsgi_app(self, environ, start_response):
            return self._dispatch(environ, start_response)

        def __call__(self, environ, start_response):
            return self.wsgi_app(environ, start_response)

        def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
            self.debug = debug
            with make_server(host, port, self) as server:
                print(f" * Servidor mini Flask em http://{host}:{port}")
                server.serve_forever()

        def _url_for(self, endpoint: str, **values) -> str:
            if endpoint not in self._endpoints:
                raise KeyError(f"Endpoint '{endpoint}' não encontrado")
            return self._endpoints[endpoint].build_url(values)

    def url_for(endpoint: str, **values) -> str:
        if _CURRENT_APP is None:
            raise RuntimeError("Aplicação não inicializada")
        return _CURRENT_APP._url_for(endpoint, **values)

# ---------------------------------------------------------------------------
# Configuração geral do app
# ---------------------------------------------------------------------------
app = Flask(__name__)
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "organograma.json")

BASE_TEMPLATE = """
<!doctype html>
<html lang=\"pt-br\">
<head>
    <meta charset=\"utf-8\">
    <title>Organograma Funcional</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f6f8fb; color: #333; }
        header { background: #0d47a1; color: white; padding: 1rem 2rem; }
        header h1 { margin: 0; }
        nav { margin-top: .5rem; }
        nav a { color: #ffeb3b; margin-right: 1rem; text-decoration: none; font-weight: bold; }
        nav a:hover { text-decoration: underline; }
        main { padding: 2rem; }
        footer { text-align: center; padding: 1rem; background: #0d47a1; color: white; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { border: 1px solid #ccc; padding: .5rem; text-align: left; }
        th { background: #e3f2fd; }
        .btn { display: inline-block; padding: .5rem 1rem; background: #0d47a1; color: white; border-radius: 4px; text-decoration: none; }
        .btn:hover { background: #1565c0; }
        form { max-width: 600px; }
        label { display: block; margin-top: 1rem; }
        input[type=text], select { width: 100%; padding: .5rem; margin-top: .25rem; border: 1px solid #ccc; border-radius: 4px; }
        button { margin-top: 1rem; padding: .5rem 1.5rem; border: none; border-radius: 4px; background: #0d47a1; color: white; cursor: pointer; }
        button:hover { background: #1565c0; }
        .tree { display: flex; justify-content: center; }
        .tree ul { list-style: none; padding-left: 1.5rem; position: relative; }
        .tree ul::before { content: ''; position: absolute; top: 0; left: 0; border-left: 1px solid #999; height: 100%; }
        .tree li { margin: 0; padding: 1rem; position: relative; }
        .tree li::before { content: ''; position: absolute; top: 0; left: -1.2rem; width: 1.2rem; border-top: 1px solid #999; }
        .node { background: white; border: 1px solid #0d47a1; border-radius: 4px; padding: .5rem 1rem; min-width: 180px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .message { padding: 1rem; background: #fff3cd; border: 1px solid #ffeeba; border-radius: 4px; color: #856404; }
    </style>
</head>
<body>
<header>
    <h1>Organograma Funcional</h1>
    <nav>
        <a href=\"{{ link_index }}\">Início</a>
        <a href=\"{{ link_organograma }}\">Organograma</a>
        <a href=\"{{ link_cargos }}\">Cargos</a>
        <a href=\"{{ link_novo }}\">Novo cargo</a>
        <a href=\"{{ link_exportar }}\">Exportar JSON</a>
    </nav>
</header>
<main>
    {{ content }}
</main>
<footer>
    &copy; {{ year }} - Organograma Funcional
</footer>
</body>
</html>
"""


def render_page(content: str) -> str:
    navigation = {
        "link_index": url_for("index"),
        "link_organograma": url_for("organograma"),
        "link_cargos": url_for("listar_cargos"),
        "link_novo": url_for("novo_cargo"),
        "link_exportar": url_for("exportar"),
    }
    context = {"content": content, "year": datetime.now().year, **navigation}
    return render_template_string(BASE_TEMPLATE, **context)


# ------------------------ Funções utilitárias ------------------------
def load_data() -> List[Dict]:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except json.JSONDecodeError:
        return []


def save_data(data: List[Dict]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def get_next_id(data: List[Dict]) -> int:
    if not data:
        return 1
    return max(int(item["id"]) for item in data) + 1


def find_role(data: List[Dict], role_id: int) -> Optional[Dict]:
    for item in data:
        if int(item["id"]) == int(role_id):
            return item
    return None


def build_tree(nodes: List[Dict]) -> List[Dict]:
    node_map: Dict[int, Dict] = {}
    for node in nodes:
        node_copy = {**node, "children": []}
        node_map[int(node["id"])] = node_copy
    roots: List[Dict] = []
    for node in node_map.values():
        parent_id = node.get("id_pai")
        if parent_id in (None, "", "null"):
            roots.append(node)
        else:
            try:
                parent = node_map.get(int(parent_id))
            except (TypeError, ValueError):
                parent = None
            if parent:
                parent["children"].append(node)
            else:
                roots.append(node)
    return roots


def render_tree_html(nodes: List[Dict]) -> str:
    if not nodes:
        return ""
    html_parts = ["<ul>"]
    for node in nodes:
        nome = html.escape(str(node.get("nome", "")))
        cargo = html.escape(str(node.get("cargo", "")))
        departamento = html.escape(str(node.get("departamento", "")))
        html_parts.append("<li>")
        html_parts.append(
            f"<div class='node'><strong>{nome}</strong><br>{cargo}<br><small>{departamento}</small></div>"
        )
        if node.get("children"):
            html_parts.append(render_tree_html(node["children"]))
        html_parts.append("</li>")
    html_parts.append("</ul>")
    return "".join(html_parts)


# ------------------------ Rotas ------------------------
@app.route("/")
def index():
    content = f"""
    <section>
        <h2>Bem-vindo!</h2>
        <p>Esta aplicação permite cadastrar cargos, definir hierarquias e visualizar o organograma funcional.</p>
        <p>Use o menu superior para navegar entre as funcionalidades principais.</p>
        <div>
            <a class=\"btn\" href=\"{html.escape(url_for('organograma'))}\">Ver organograma</a>
            <a class=\"btn\" href=\"{html.escape(url_for('listar_cargos'))}\" style=\"margin-left:1rem;\">Listar cargos</a>
            <a class=\"btn\" href=\"{html.escape(url_for('novo_cargo'))}\" style=\"margin-left:1rem;\">Adicionar cargo</a>
        </div>
    </section>
    """
    return render_page(content)


@app.route("/organograma")
def organograma():
    data = load_data()
    tree = build_tree(data)
    tree_html = render_tree_html(tree) if tree else "<p>Não há cargos cadastrados.</p>"
    content = f"""
    <section>
        <h2>Organograma</h2>
        <div class=\"tree\">
            {tree_html}
        </div>
    </section>
    """
    return render_page(content)


@app.route("/cargos")
def listar_cargos():
    data = load_data()
    id_to_nome = {int(item["id"]): str(item["nome"]) for item in data if str(item.get("id"))}
    if data:
        rows = []
        for item in data:
            item_id = int(item["id"])
            parent_id = item.get("id_pai")
            superior = "—"
            if parent_id not in (None, "", "null"):
                try:
                    superior = id_to_nome.get(int(parent_id), "—")
                except (TypeError, ValueError):
                    superior = "—"
            edit_url = html.escape(url_for("editar_cargo", role_id=item_id))
            delete_url = html.escape(url_for("deletar_cargo", role_id=item_id))
            rows.append(
                "<tr>"
                f"<td>{item_id}</td>"
                f"<td>{html.escape(str(item.get('nome', '')))}</td>"
                f"<td>{html.escape(str(item.get('cargo', '')))}</td>"
                f"<td>{html.escape(str(item.get('departamento', '')))}</td>"
                f"<td>{html.escape(superior)}</td>"
                f"<td><a href='{edit_url}'>Editar</a> | "
                f"<a href='{delete_url}' onclick=\"return confirm('Tem certeza que deseja excluir?');\">Excluir</a></td>"
                "</tr>"
            )
        table_html = """
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Nome</th>
                    <th>Cargo</th>
                    <th>Departamento</th>
                    <th>Superior</th>
                    <th>Ações</th>
                </tr>
            </thead>
            <tbody>
        """ + "".join(rows) + "</tbody></table>"
    else:
        table_html = "<p>Não há cargos cadastrados.</p>"
    content = f"""
    <section>
        <h2>Lista de cargos</h2>
        {table_html}
    </section>
    """
    return render_page(content)


@app.route("/cargos/novo", methods=["GET", "POST"])
def novo_cargo():
    data = load_data()
    if request.method == "POST":
        novo = {
            "id": get_next_id(data),
            "nome": request.form.get("nome", "").strip(),
            "cargo": request.form.get("cargo", "").strip(),
            "departamento": request.form.get("departamento", "").strip(),
            "id_pai": request.form.get("id_pai") or None,
        }
        if novo["id_pai"] not in (None, "", "null"):
            novo["id_pai"] = int(novo["id_pai"])
        else:
            novo["id_pai"] = None
        save_data(data + [novo])
        return redirect(url_for("listar_cargos"))

    options = ["<option value=\"\">Nenhum (topo)</option>"]
    for item in data:
        label = f"{item['nome']} - {item['cargo']}"
        options.append(
            f"<option value=\"{int(item['id'])}\">{html.escape(label)}</option>"
        )
    options_html = "".join(options)
    content = f"""
    <section>
        <h2>Novo cargo</h2>
        <form method=\"post\">
            <label>Nome completo
                <input type=\"text\" name=\"nome\" required>
            </label>
            <label>Cargo
                <input type=\"text\" name=\"cargo\" required>
            </label>
            <label>Departamento
                <input type=\"text\" name=\"departamento\" required>
            </label>
            <label>Superior hierárquico
                <select name=\"id_pai\">
                    {options_html}
                </select>
            </label>
            <button type=\"submit\">Salvar</button>
        </form>
    </section>
    """
    return render_page(content)


@app.route("/cargos/<int:role_id>/editar", methods=["GET", "POST"])
def editar_cargo(role_id: int):
    data = load_data()
    role = find_role(data, role_id)
    if not role:
        return render_page("<p class='message'>Cargo não encontrado.</p>")

    if request.method == "POST":
        role["nome"] = request.form.get("nome", role["nome"]).strip()
        role["cargo"] = request.form.get("cargo", role["cargo"]).strip()
        role["departamento"] = request.form.get("departamento", role["departamento"]).strip()
        parent_raw = request.form.get("id_pai")
        if parent_raw not in (None, "", "null"):
            role["id_pai"] = int(parent_raw)
        else:
            role["id_pai"] = None
        save_data(data)
        return redirect(url_for("listar_cargos"))

    options = ["<option value=\"\">Nenhum (topo)</option>"]
    role_parent = role.get("id_pai")
    if role_parent in ("", "null"):
        role_parent = None
    elif role_parent is not None:
        try:
            role_parent = int(role_parent)
        except (TypeError, ValueError):
            role_parent = None
    for item in data:
        item_id = int(item["id"])
        if item_id == int(role["id"]):
            continue
        selected = " selected" if role_parent == item_id else ""
        label = f"{item['nome']} - {item['cargo']}"
        options.append(
            f"<option value=\"{item_id}\"{selected}>{html.escape(label)}</option>"
        )
    options_html = "".join(options)
    nome_value = html.escape(role.get("nome", ""), quote=True)
    cargo_value = html.escape(role.get("cargo", ""), quote=True)
    departamento_value = html.escape(role.get("departamento", ""), quote=True)
    content = f"""
    <section>
        <h2>Editar cargo</h2>
        <form method=\"post\">
            <label>Nome completo
                <input type=\"text\" name=\"nome\" value=\"{nome_value}\" required>
            </label>
            <label>Cargo
                <input type=\"text\" name=\"cargo\" value=\"{cargo_value}\" required>
            </label>
            <label>Departamento
                <input type=\"text\" name=\"departamento\" value=\"{departamento_value}\" required>
            </label>
            <label>Superior hierárquico
                <select name=\"id_pai\">
                    {options_html}
                </select>
            </label>
            <button type=\"submit\">Atualizar</button>
        </form>
    </section>
    """
    return render_page(content)


@app.route("/cargos/<int:role_id>/deletar")
def deletar_cargo(role_id: int):
    data = load_data()
    role = find_role(data, role_id)
    if not role:
        return render_page("<p class='message'>Cargo não encontrado.</p>")

    has_children = False
    for item in data:
        parent_value = item.get("id_pai")
        if parent_value in (None, "", "null"):
            continue
        try:
            parent_value = int(parent_value)
        except (TypeError, ValueError):
            parent_value = None
        if parent_value == role_id:
            has_children = True
            break
    if has_children:
        content = f"""
        <section>
            <h2>Não é possível excluir</h2>
            <p class=\"message\">O cargo <strong>{html.escape(role['nome'])}</strong> possui subordinados. Remova ou atualize os subordinados antes de deletá-lo.</p>
            <a class=\"btn\" href=\"{html.escape(url_for('listar_cargos'))}\">Voltar</a>
        </section>
        """
        return render_page(content)

    data = [item for item in data if int(item["id"]) != role_id]
    save_data(data)
    return redirect(url_for("listar_cargos"))


@app.route("/exportar")
def exportar():
    data = load_data()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True)

# Dependências: pip install flask
# Execução: python app.py
# A aplicação ficará disponível em http://127.0.0.1:5000
