from flask import Flask, render_template, request, redirect
from datetime import datetime, timedelta
import sqlite3

app = Flask(__name__)

def conectar():
    conn = sqlite3.connect("database.db")
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
        erros INTEGER DEFAULT 0
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
                    WHEN flashcards.proxima_revisao IS NULL 
                    OR flashcards.proxima_revisao <= ?
                    THEN 1 ELSE 0 
                END
            ) as revisar
        FROM materias
        LEFT JOIN flashcards
        ON materias.id = flashcards.materia_id
        GROUP BY materias.id
    """, (hoje,)).fetchall()

    conn.close()

    return render_template("index.html", materias=materias)

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

    conn.commit()
    conn.close()

    return {"status": "ok", "dias": dias, "data": proxima_data_str}
@app.route("/dashboard/<int:id>")
def dashboard(id):
    from datetime import datetime

    conn = conectar()

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
        dificeis=dificeis
    )

if __name__ == "__main__":
    app.run(debug=True)
