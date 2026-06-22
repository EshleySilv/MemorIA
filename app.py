from flask import Flask, render_template, request, redirect
from datetime import datetime, timedelta
import sqlite3
import google.generativeai as genai
from pypdf import PdfReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file

from dotenv import load_dotenv
import os

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


app = Flask(__name__)


genai.configure(api_key=GEMINI_API_KEY)

modelo = genai.GenerativeModel("gemini-flash-latest")

def conectar():
    conn = sqlite3.connect("database.db", timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def criar_tabelas():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS materias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        materia_id INTEGER,
        pergunta TEXT NOT NULL,
        resposta TEXT NOT NULL,
        dificuldade TEXT DEFAULT 'nova',
        proxima_revisao TEXT,
        acertos INTEGER DEFAULT 0,
        erros INTEGER DEFAULT 0,
        tempo_total REAL DEFAULT 0,
        visualizacoes INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

criar_tabelas()

from datetime import datetime

@app.route("/")
def home():
    conn = conectar()

    hoje = datetime.now().strftime("%Y-%m-%d")

    materias = conn.execute("""
        SELECT 
            materias.id,
            materias.nome,
            COUNT(flashcards.id) as total,
            SUM(
                CASE
                    WHEN flashcards.id IS NOT NULL
                    AND (
                        flashcards.proxima_revisao IS NULL
                        OR flashcards.proxima_revisao <= ?
                    )
                    THEN 1
                    ELSE 0
                END
            ) as revisar
        FROM materias
        LEFT JOIN flashcards
        ON materias.id = flashcards.materia_id
        GROUP BY materias.id
    """, (hoje,)).fetchall()

    conn.close()

    return render_template("index.html", materias=materias)

@app.route("/criar-materia", methods=["POST"])
def criar_materia():

    nome = request.form["nome"]

    conn = conectar()

    conn.execute(
        "INSERT INTO materias (nome) VALUES (?)",
        (nome,)
    )

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/materia/<int:id>")
def abrir_materia(id):
    conn = conectar()

    materia = conn.execute(
        "SELECT * FROM materias WHERE id = ?",
        (id,)
    ).fetchone()

    flashcards = conn.execute(
        "SELECT * FROM flashcards WHERE materia_id = ?",
        (id,)
    ).fetchall()

    conn.close()

    return render_template(
        "materia.html",
        materia=materia,
        flashcards=flashcards
    )

@app.route("/criar-flashcard/<int:id>", methods=["POST"])
def criar_flashcard(id):
    from flask import request, redirect

    pergunta = request.form["pergunta"]
    resposta = request.form["resposta"]

    conn = conectar()

    conn.execute("""
        INSERT INTO flashcards
        (materia_id, pergunta, resposta)
        VALUES (?, ?, ?)
    """, (id, pergunta, resposta))

    conn.commit()
    conn.close()

    return redirect(f"/materia/{id}")

@app.route("/estudar/<int:id>")
def estudar(id):
    conn = conectar()

    materia = conn.execute(
        "SELECT * FROM materias WHERE id = ?",
        (id,)
    ).fetchone()

    from datetime import datetime

    hoje = datetime.now().strftime("%Y-%m-%d")

    flashcards = conn.execute("""
        SELECT * FROM flashcards
        WHERE materia_id = ?
        AND (
            proxima_revisao IS NULL
            OR proxima_revisao <= ?
        )
    """, (id, hoje)).fetchall()

    conn.close()

    return render_template(
        "estudar.html",
        materia=materia,
        flashcards=flashcards
    )

@app.route("/excluir-materia/<int:id>")
def excluir_materia(id):
    conn = conectar()

    conn.execute("DELETE FROM flashcards WHERE materia_id = ?", (id,))
    conn.execute("DELETE FROM materias WHERE id = ?", (id,))

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/excluir-card/<int:id>/<int:materia_id>")
def excluir_card(id, materia_id):
    conn = conectar()

    conn.execute("DELETE FROM flashcards WHERE id = ?", (id,))

    conn.commit()
    conn.close()

    return redirect(f"/materia/{materia_id}")

@app.route("/avaliar", methods=["POST"])
def avaliar():
    from flask import request

    data = request.get_json()

    card_id = data["card_id"]
    tipo = data["tipo"]
    tempo = float(data.get("tempo", 0))

    # lógica simples de dias
    if tipo == "facil":
        dias = 7
    elif tipo == "medio":
        dias = 3
    elif tipo == "dificil":
        dias = 1
    else:
        dias = 0

    # calcula data futura
    proxima_data = datetime.now() + timedelta(days=dias)
    proxima_data_str = proxima_data.strftime("%Y-%m-%d")

    conn = conectar()

    conn.execute("PRAGMA journal_mode=WAL")

    if tipo == "errei":
        conn.execute("""
            UPDATE flashcards
            SET erros = erros + 1,
                dificuldade = ?,
                proxima_revisao = ?
            WHERE id = ?
        """, ("dificil", proxima_data_str, card_id))
    else:
        conn.execute("""
            UPDATE flashcards
            SET acertos = acertos + 1,
                dificuldade = ?,
                proxima_revisao = ?
            WHERE id = ?
        """, (tipo, proxima_data_str, card_id))
    conn.execute("""
    UPDATE flashcards
    SET
        tempo_total = tempo_total + ?,
        visualizacoes = visualizacoes + 1
    WHERE id = ?
    """, (tempo, card_id))

    conn.commit()
    conn.close()

    return {"status": "ok", "dias": dias, "data": proxima_data_str}
@app.route("/dashboard/<int:id>")
def dashboard(id):
    from datetime import datetime

    conn = conectar()
    tempo_medio = conn.execute("""
    SELECT
    AVG(
        CASE
            WHEN visualizacoes > 0
            THEN tempo_total / visualizacoes
        END
    )
    FROM flashcards
    WHERE materia_id = ?
    """, (id,)).fetchone()[0]

    tempo_medio = round(tempo_medio or 0, 1)

    materia = conn.execute(
        "SELECT * FROM materias WHERE id = ?",
        (id,)
    ).fetchone()

    dados = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(acertos) as acertos,
            SUM(erros) as erros
        FROM flashcards
        WHERE materia_id = ?
    """, (id,)).fetchone()

    total = dados["total"] or 0
    acertos = dados["acertos"] or 0
    erros = dados["erros"] or 0

    taxa = 0
    if (acertos + erros) > 0:
        taxa = int((acertos / (acertos + erros)) * 100)

    hoje = datetime.now().strftime("%Y-%m-%d")

    revisar_hoje = conn.execute("""
        SELECT COUNT(*) as total
        FROM flashcards
        WHERE materia_id = ?
        AND (
            proxima_revisao IS NULL
            OR proxima_revisao <= ?
        )
    """, (id, hoje)).fetchone()["total"]

    dificeis = conn.execute("""
        SELECT pergunta, erros
        FROM flashcards
        WHERE materia_id = ?
        ORDER BY erros DESC
        LIMIT 3
    """, (id,)).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        materia=materia,
        total=total,
        acertos=acertos,
        erros=erros,
        taxa=taxa,
        revisar_hoje=revisar_hoje,
        dificeis=dificeis,
        tempo_medio=tempo_medio
    )



@app.route("/gerar-flashcards-ia/<int:id>", methods=["POST"])
def gerar_flashcards_ia(id):

    texto = request.form.get("texto", "").strip()
    quantidade = request.form.get("quantidade", "5")

    arquivo = request.files.get("arquivo")

    conteudo = ""

    if arquivo and arquivo.filename:

        caminho = f"uploads/{arquivo.filename}"
        arquivo.save(caminho)

        leitor = PdfReader(caminho)

        for pagina in leitor.pages:
            conteudo += pagina.extract_text() or ""

        conteudo = conteudo[:15000]
        print("Usando PDF")

    elif texto:

        conteudo = texto
        print("Usando resumo")

    else:
        return redirect(f"/materia/{id}")
    
    prompt = f"""
    Gere EXATAMENTE {quantidade} flashcards.

    Conteúdo:

    {conteudo}

    Responda SOMENTE neste formato:

    PERGUNTA: pergunta aqui
    RESPOSTA: resposta aqui

    PERGUNTA: pergunta aqui
    RESPOSTA: resposta aqui
    """

    resposta = modelo.generate_content(prompt)

    texto_gerado = resposta.text

    conn = conectar()

    blocos = texto_gerado.split("PERGUNTA:")

    for bloco in blocos:

        bloco = bloco.strip()

        if not bloco:
            continue

        partes = bloco.split("RESPOSTA:")

        if len(partes) != 2:
            continue

        pergunta = partes[0].strip()
        resposta_card = partes[1].strip()

        conn.execute("""
            INSERT INTO flashcards
            (materia_id, pergunta, resposta)
            VALUES (?, ?, ?)
        """, (id, pergunta, resposta_card))

    conn.commit()
    conn.close()

    return redirect(f"/materia/{id}")

@app.route("/editar-card/<int:id>")
def editar_card(id):

    conn = conectar()

    card = conn.execute("""
        SELECT *
        FROM flashcards
        WHERE id = ?
    """, (id,)).fetchone()

    conn.close()

    return render_template(
        "editar_card.html",
        card=card
    )

@app.route("/salvar-card/<int:id>", methods=["POST"])
def salvar_card(id):

    pergunta = request.form["pergunta"]
    resposta = request.form["resposta"]

    conn = conectar()

    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        UPDATE flashcards
        SET pergunta = ?, resposta = ?
        WHERE id = ?
    """, (pergunta, resposta, id))

    conn.commit()

    materia_id = conn.execute("""
        SELECT materia_id
        FROM flashcards
        WHERE id = ?
    """, (id,)).fetchone()[0]

    conn.close()

    return redirect(f"/materia/{materia_id}")

@app.route("/exportar-pdf/<int:id>")
def exportar_pdf(id):

    conn = conectar()

    materia = conn.execute("""
        SELECT *
        FROM materias
        WHERE id = ?
    """, (id,)).fetchone()

    flashcards = conn.execute("""
        SELECT *
        FROM flashcards
        WHERE materia_id = ?
    """, (id,)).fetchall()

    conn.close()

    nome_arquivo = f"{materia['nome']}.pdf"

    pdf = SimpleDocTemplate(nome_arquivo)

    estilos = getSampleStyleSheet()

    conteudo = []

    conteudo.append(
        Paragraph(
            f"Deck: {materia['nome']}",
            estilos["Title"]
        )
    )

    conteudo.append(Spacer(1, 20))

    for card in flashcards:

        conteudo.append(
            Paragraph(
                f"<b>Pergunta:</b> {card['pergunta']}",
                estilos["BodyText"]
            )
        )

        conteudo.append(
            Paragraph(
                f"<b>Resposta:</b> {card['resposta']}",
                estilos["BodyText"]
            )
        )

        conteudo.append(Spacer(1, 12))

    pdf.build(conteudo)

    return send_file(
        nome_arquivo,
        as_attachment=True
    )

if __name__ == "__main__":
    app.run(debug=True)
