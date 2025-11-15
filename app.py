import json
import os
from datetime import datetime
from typing import List, Dict, Optional

from flask import Flask, render_template_string, request, redirect, url_for, Response

app = Flask(__name__)

# Caminho do arquivo usado para persistir o organograma.
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "organograma.json")

# Template base utilizado em todas as páginas. Todo o HTML/CSS da aplicação está aqui.
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
        <a href=\"{{ url_for('index') }}\">Início</a>
        <a href=\"{{ url_for('organograma') }}\">Organograma</a>
        <a href=\"{{ url_for('listar_cargos') }}\">Cargos</a>
        <a href=\"{{ url_for('novo_cargo') }}\">Novo cargo</a>
        <a href=\"{{ url_for('exportar') }}\">Exportar JSON</a>
    </nav>
</header>
<main>
    {{ content|safe }}
</main>
<footer>
    &copy; {{ year }} - Organograma Funcional
</footer>
</body>
</html>
"""


def render_page(content_template: str, **context) -> str:
    """Renderiza um conteúdo específico dentro do template base."""
    content_html = render_template_string(content_template, **context)
    current_year = datetime.now().year
    return render_template_string(BASE_TEMPLATE, content=content_html, year=current_year)


# ------------------------ Funções utilitárias ------------------------
def load_data() -> List[Dict]:
    """Carrega o organograma do disco. Retorna lista vazia se não existir."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except json.JSONDecodeError:
        # Arquivo existe mas está inválido: considerar lista vazia.
        return []


def save_data(data: List[Dict]) -> None:
    """Salva o organograma no disco com indentação amigável."""
    with open(DATA_FILE, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def get_next_id(data: List[Dict]) -> int:
    """Gera o próximo ID incremental."""
    if not data:
        return 1
    return max(int(item["id"]) for item in data) + 1


def find_role(data: List[Dict], role_id: int) -> Optional[Dict]:
    """Localiza um cargo pelo ID."""
    for item in data:
        if int(item["id"]) == int(role_id):
            return item
    return None


def build_tree(nodes: List[Dict]) -> List[Dict]:
    """Transforma a lista plana em uma árvore hierárquica."""
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
            parent = node_map.get(int(parent_id))
            if parent:
                parent["children"].append(node)
            else:
                roots.append(node)
    return roots


def render_tree_html(nodes: List[Dict]) -> str:
    """Gera HTML recursivo para a árvore."""
    if not nodes:
        return ""
    html_parts = ["<ul>"]
    for node in nodes:
        html_parts.append("<li>")
        html_parts.append(
            f"<div class='node'><strong>{node['nome']}</strong><br>"
            f"{node['cargo']}<br><small>{node['departamento']}</small></div>"
        )
        if node.get("children"):
            html_parts.append(render_tree_html(node["children"]))
        html_parts.append("</li>")
    html_parts.append("</ul>")
    return "".join(html_parts)


# ------------------------ Rotas ------------------------
@app.route("/")
def index():
    content = """
    <section>
        <h2>Bem-vindo!</h2>
        <p>Esta aplicação permite cadastrar cargos, definir hierarquias e visualizar o organograma funcional.</p>
        <p>Use o menu superior para navegar entre as funcionalidades principais.</p>
        <div>
            <a class=\"btn\" href=\"{{ url_for('organograma') }}\">Ver organograma</a>
            <a class=\"btn\" href=\"{{ url_for('listar_cargos') }}\" style=\"margin-left:1rem;\">Listar cargos</a>
            <a class=\"btn\" href=\"{{ url_for('novo_cargo') }}\" style=\"margin-left:1rem;\">Adicionar cargo</a>
        </div>
    </section>
    """
    return render_page(content)


@app.route("/organograma")
def organograma():
    data = load_data()
    tree = build_tree(data)
    tree_html = render_tree_html(tree) if tree else "<p>Não há cargos cadastrados.</p>"
    content = """
    <section>
        <h2>Organograma</h2>
        <div class=\"tree\">
            {{ tree_html|safe }}
        </div>
    </section>
    """
    return render_page(content, tree_html=tree_html)


@app.route("/cargos")
def listar_cargos():
    data = load_data()
    id_to_nome = {int(item["id"]): item["nome"] for item in data}
    content = """
    <section>
        <h2>Lista de cargos</h2>
        {% if data %}
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
            {% for item in data %}
                <tr>
                    <td>{{ item.id }}</td>
                    <td>{{ item.nome }}</td>
                    <td>{{ item.cargo }}</td>
                    <td>{{ item.departamento }}</td>
                    <td>{{ id_to_nome.get(item.id_pai|int) if item.id_pai else '—' }}</td>
                    <td>
                        <a href=\"{{ url_for('editar_cargo', role_id=item.id) }}\">Editar</a> |
                        <a href=\"{{ url_for('deletar_cargo', role_id=item.id) }}\" onclick=\"return confirm('Tem certeza que deseja excluir?');\">Excluir</a>
                    </td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
            <p>Não há cargos cadastrados.</p>
        {% endif %}
    </section>
    """
    return render_page(content, data=data, id_to_nome=id_to_nome)


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
        if novo["id_pai"]:
            novo["id_pai"] = int(novo["id_pai"])
        save_data(data + [novo])
        return redirect(url_for("listar_cargos"))

    content = """
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
                    <option value=\"\">Nenhum (topo)</option>
                    {% for item in data %}
                        <option value=\"{{ item.id }}\">{{ item.nome }} - {{ item.cargo }}</option>
                    {% endfor %}
                </select>
            </label>
            <button type=\"submit\">Salvar</button>
        </form>
    </section>
    """
    return render_page(content, data=data)


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
        if parent_raw:
            role["id_pai"] = int(parent_raw)
        else:
            role["id_pai"] = None
        save_data(data)
        return redirect(url_for("listar_cargos"))

    content = """
    <section>
        <h2>Editar cargo</h2>
        <form method=\"post\">
            <label>Nome completo
                <input type=\"text\" name=\"nome\" value=\"{{ role.nome }}\" required>
            </label>
            <label>Cargo
                <input type=\"text\" name=\"cargo\" value=\"{{ role.cargo }}\" required>
            </label>
            <label>Departamento
                <input type=\"text\" name=\"departamento\" value=\"{{ role.departamento }}\" required>
            </label>
            <label>Superior hierárquico
                <select name=\"id_pai\">
                    <option value=\"\">Nenhum (topo)</option>
                    {% for item in data %}
                        {% if item.id != role.id %}
                            <option value=\"{{ item.id }}\" {% if item.id == role.id_pai %}selected{% endif %}>{{ item.nome }} - {{ item.cargo }}</option>
                        {% endif %}
                    {% endfor %}
                </select>
            </label>
            <button type=\"submit\">Atualizar</button>
        </form>
    </section>
    """
    return render_page(content, data=data, role=role)


@app.route("/cargos/<int:role_id>/deletar")
def deletar_cargo(role_id: int):
    data = load_data()
    role = find_role(data, role_id)
    if not role:
        return render_page("<p class='message'>Cargo não encontrado.</p>")

    # Verifica se há subordinados vinculados ao cargo.
    has_children = any(item.get("id_pai") == role_id for item in data)
    if has_children:
        message = """
        <section>
            <h2>Não é possível excluir</h2>
            <p class=\"message\">O cargo <strong>{{ role.nome }}</strong> possui subordinados. Remova ou atualize os subordinados antes de deletá-lo.</p>
            <a class=\"btn\" href=\"{{ url_for('listar_cargos') }}\">Voltar</a>
        </section>
        """
        return render_page(message, role=role)

    # Remove o cargo da lista e salva.
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
