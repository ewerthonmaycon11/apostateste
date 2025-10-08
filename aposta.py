from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2, psycopg2.extras
from datetime import datetime
import os
import json

app = Flask(__name__)
app.secret_key = "supersegredo123"

# ------------------ Config Banco ------------------
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://apostaonline_user:rM2mWO5FaaCmMgXEmp2pharDko1Cc1SE@dpg-d3e71fh5pdvs738qrmn0-a.oregon-postgres.render.com/apostaonline"
)
def get_db_connection():
    DB_URL = os.getenv("DATABASE_URL", "postgresql://apostaonline_user:rM2mWO5FaaCmMgXEmp2pharDko1Cc1SE@dpg-d3e71fh5pdvs738qrmn0-a.oregon-postgres.render.com/apostaonline")
    conn = psycopg2.connect(DB_URL)
    return conn
# ------------------ Helpers DB ------------------
def get_conn():
    # Usando RealDictCursor em todos os lugares para garantir que os resultados venham como dicionários
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def row_to_dict(row):
    if row is None:
        return None
    # Como usamos RealDictCursor, já é um dicionário, mas mantemos o retorno
    return dict(row)

# ------------------ Inicializa DB ------------------
def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Usuários
    c.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        nome TEXT,
        email TEXT UNIQUE,
        senha TEXT,
        saldo REAL DEFAULT 0,
        is_admin INTEGER DEFAULT 0,
        criado_em TEXT
    );
    ''')

    # Jogos principais
    c.execute('''
    CREATE TABLE IF NOT EXISTS jogos (
        id SERIAL PRIMARY KEY,
        time_a TEXT NOT NULL,
        time_b TEXT NOT NULL,
        odd_a REAL NOT NULL,
        odd_x REAL NOT NULL,
        odd_b REAL NOT NULL,
        data_hora TEXT,
        ativo INTEGER DEFAULT 1,
        criado_em TEXT
    );
    ''')

    # Extras
    c.execute('''
    CREATE TABLE IF NOT EXISTS extras (
        id SERIAL PRIMARY KEY,
        jogo_id INTEGER NOT NULL REFERENCES jogos(id) ON DELETE CASCADE,
        descricao TEXT NOT NULL,
        odd REAL NOT NULL,
        criado_em TEXT
    );
    ''')

    # Apostas
    c.execute('''
    CREATE TABLE IF NOT EXISTS bets (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        stake REAL NOT NULL,
        total_odd REAL NOT NULL,
        potential REAL NOT NULL,
        status TEXT DEFAULT 'pendente',
        criado_em TEXT
    );
    ''')

    # Seleções de Apostas
    # NOTA: Removemos as colunas time_a/time_b/data_hora pois o LEFT JOIN já faz o trabalho,
    # garantindo que a consulta na rota /historico busque os dados ATUAIS do jogo.
    # Se você quiser armazenar um "snapshot" dos dados do jogo no momento da aposta,
    # reintroduza as colunas e salve-as no INSERT abaixo.
    c.execute('''
    CREATE TABLE IF NOT EXISTS bet_selections (
        id SERIAL PRIMARY KEY,
        bet_id INTEGER NOT NULL REFERENCES bets(id) ON DELETE CASCADE,
        jogo_id INTEGER REFERENCES jogos(id) ON DELETE CASCADE,
        tipo TEXT,
        escolha TEXT,
        odd REAL,
        resultado TEXT
    );
    ''')

    # Transações
    c.execute('''
    CREATE TABLE IF NOT EXISTS transacoes (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL,
        valor REAL NOT NULL,
        status TEXT DEFAULT 'pendente',
        criado_em TEXT
    );
    ''')

    # Admin padrão
    c.execute("SELECT id FROM usuarios WHERE is_admin=1 LIMIT 1")
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO usuarios (nome, email, senha, saldo, is_admin, criado_em) VALUES (%s,%s,%s,%s,%s,%s)",
            ("admin", "admin", "1234", 0.0, 1, datetime.now().isoformat())
        )

    conn.commit()
    conn.close()

# Inicializa DB
init_db()

# ------------------ Utilitários ------------------
def calc_total_odd(selections):
    total = 1.0
    for s in selections:
        total *= float(s)
    return round(total, 6)

def calc_potential(stake, total_odd):
    return round(stake * total_odd, 2)

# ------------------ ROTAS ------------------
@app.route("/migrar_betselections")
def migrar_betselections():
    try:
        conn = get_conn()
        c = conn.cursor()
        
        # Adiciona colunas, mas ignora erro caso já existam
        comandos = [
            "ALTER TABLE bet_selections ADD COLUMN IF NOT EXISTS time_a TEXT",
            "ALTER TABLE bet_selections ADD COLUMN IF NOT EXISTS time_b TEXT",
            "ALTER TABLE bet_selections ADD COLUMN IF NOT EXISTS data_hora TEXT"
        ]
        
        for cmd in comandos:
            c.execute(cmd)

        conn.commit()
        conn.close()
        return "Migração concluída com sucesso 🚀"
    except Exception as e:
        return f"Erro: {e}"


@app.route("/update_schema")
def update_schema():
    # Removendo a tentativa de ALTER TABLE, pois o LEFT JOIN no /historico é a abordagem correta.
    # Se quiser forçar o snapshot do jogo na aposta, você precisará reintroduzir o ALTER TABLE aqui
    # e ajustar os INSERTs nas rotas /apostar e /aposta_multipla
    return "O uso de LEFT JOIN foi mantido para carregar o histórico. Nenhuma alteração de schema necessária."

@app.route("/")
def index():
    if session.get("usuario_id"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_field = request.form.get("email") or request.form.get("username") or request.form.get("usuario")
        senha = request.form.get("senha") or request.form.get("password")
        if not login_field or not senha:
            flash("Preencha credenciais.", "warning")
            return redirect(url_for("login"))

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM usuarios WHERE (email=%s OR nome=%s) AND senha=%s", (login_field, login_field, senha))
        user = c.fetchone()
        conn.close()
        if user:
            session["usuario_id"] = user["id"]
            session["usuario_nome"] = user["nome"]
            session["is_admin"] = bool(user["is_admin"])
            flash(f"Bem-vindo, {user['nome'] or user['email']}!", "success")
            if user["is_admin"]:
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("dashboard"))
        flash("Credenciais inválidas.", "danger")
    return render_template("login.html")

@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    if request.method == "POST":
        nome = request.form.get("nome") or request.form.get("username")
        email = request.form.get("email")
        senha = request.form.get("senha")
        if not nome or not (email or nome) or not senha:
            flash("Preencha todos os campos.", "warning")
            return redirect(url_for("registrar"))
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO usuarios (nome, email, senha, saldo, is_admin, criado_em) VALUES (%s,%s,%s,%s,%s,%s)",
                (nome, email, senha, 0.0, 0, datetime.now().isoformat())
            )
            conn.commit()
            flash("Conta criada. Faça login.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            conn.rollback()
            flash("Email já cadastrado ou erro: " + str(e), "danger")
        finally:
            conn.close()
    return render_template("register.html")

# ------------------ DASHBOARD ------------------
@app.route("/dashboard")
def dashboard():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    conn = get_conn()
    c = conn.cursor()

    # pega usuario
    c.execute("SELECT id, nome, email, saldo FROM usuarios WHERE id=%s", (session["usuario_id"],))
    usuario = c.fetchone()
    if usuario is None:
        conn.close()
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("logout"))

    # pega jogos ativos
    c.execute("SELECT * FROM jogos WHERE ativo=1 ORDER BY data_hora ASC")
    jogos_rows = c.fetchall()
    jogos = []
    for j in jogos_rows:
        jid = j["id"]

        # pega extras
        c.execute("SELECT id, descricao, odd FROM extras WHERE jogo_id=%s", (jid,))
        extras = c.fetchall()

        # trata data_hora
        dh = j["data_hora"]
        if isinstance(dh, str):
            try:
                dh = datetime.fromisoformat(dh)
            except:
                try:
                    dh = datetime.strptime(dh, "%Y-%m-%d %H:%M:%S")
                except:
                    dh = None

        jogos.append({
            "id": j["id"],
            "time_a": j["time_a"],
            "time_b": j["time_b"],
            "odd_a": j["odd_a"],
            "odd_x": j["odd_x"],
            "odd_b": j["odd_b"],
            "data_hora": dh,
            "extras": extras
        })
    conn.close()

    return render_template("dashboard.html", usuario=usuario, jogos=jogos)

# ------------------ APOSTA MÚLTIPLA (AJAX) ------------------
@app.route('/aposta_multipla', methods=['POST'])
def aposta_multipla():
    try:
        data = request.get_json()
        selecoes = data.get('selecoes', [])
        valor = float(data.get('valor', 0))
        usuario_id = session.get('usuario_id')

        if not selecoes or valor <= 0:
            return jsonify({"ok": False, "erro": "Seleções ou valor inválido"})

        conn = get_db_connection()
        cur = conn.cursor()

        # === VERIFICA SALDO ===
        cur.execute("SELECT saldo FROM usuarios WHERE id=%s", (usuario_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "erro": "Usuário não encontrado."})

        saldo_atual = float(row[0])
        if saldo_atual < valor:
            conn.close()
            return jsonify({"ok": False, "erro": "Saldo insuficiente para essa aposta."})

        # === DEBITA SALDO ===
        novo_saldo = saldo_atual - valor
        cur.execute("UPDATE usuarios SET saldo=%s WHERE id=%s", (novo_saldo, usuario_id))

        # === CALCULA ODD TOTAL ===
        retorno_total = 1.0
        for s in selecoes:
            retorno_total *= float(s['odd'])

        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # === INSERE APOSTA PRINCIPAL ===
        cur.execute(
            """
            INSERT INTO bets (usuario_id, stake, total_odd, potential, status, criado_em)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (usuario_id, valor, retorno_total, valor * retorno_total, "pendente", data_hora)
        )
        bet_id = cur.fetchone()[0]

        # === INSERE AS SELEÇÕES ===
        for s in selecoes:
            cur.execute(
                """
                INSERT INTO bet_selections
                (bet_id, jogo_id, tipo, escolha, odd, resultado, time_a, time_b, data_hora)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    bet_id,
                    s['jogo'],
                    s.get('tipo', 'principal'),
                    s['time'],
                    s['odd'],
                    "pendente",
                    s.get('time_a', s['time']),
                    s.get('time_b', ''),
                    data_hora,
                )
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "ok": True,
            "retorno": round(valor * retorno_total, 2),
            "novo_saldo": round(novo_saldo, 2)
        })

    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})




@app.route("/jogo/<int:jogo_id>")
def ver_jogo(jogo_id):
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM jogos WHERE id=%s AND ativo=1", (jogo_id,))
    jogo = c.fetchone()
    if not jogo:
        conn.close()
        flash("Jogo não encontrado.", "warning")
        return redirect(url_for("dashboard"))
    c.execute("SELECT * FROM extras WHERE jogo_id=%s", (jogo_id,))
    extras = [row_to_dict(r) for r in c.fetchall()]
    conn.close()
    return render_template("game.html", jogo=row_to_dict(jogo), extras=extras)

# API para cálculo de odds
@app.route("/api/calc", methods=["POST"])
def api_calc():
    data = request.get_json() or {}
    stake = float(data.get("stake", 0))
    selections = data.get("selections", [])  # lista de odds
    odds = [float(s.get("odd")) for s in selections if s.get("odd") is not None]
    total_odd = calc_total_odd(odds)
    potential = calc_potential(stake, total_odd)
    return jsonify({"total_odd": total_odd, "potential": potential})

# ------------------ APOSTAR (Formulário Simples) ------------------
# ------------------ APOSTAR (Formulário Simples) ------------------
@app.route("/apostar", methods=["POST"])
def apostar():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))

    usuario_id = session["usuario_id"]

    if request.is_json:
        # Se for JSON, delega para aposta_multipla (boa prática)
        return aposta_multipla() 
    else:
        # Lógica para formulário simples (POST normal)
        try:
            stake = float(request.form.get("valor", 0))
        except ValueError:
            flash("Valor de aposta inválido.", "warning")
            return redirect(url_for("dashboard"))
            
        jogo_id = request.form.get("jogo_id")
        principal = request.form.get("aposta_principal")
        extras_ids = request.form.getlist("extras")
        selections = []
        conn = get_conn()
        c = conn.cursor()
        
        # --- 1. COLETA AS SELEÇÕES E ODDs ---
        if jogo_id:
            try:
                jogo_id_int = int(jogo_id)
            except ValueError:
                conn.close()
                flash("ID de jogo inválido.", "danger")
                return redirect(url_for("dashboard"))

            c.execute("SELECT * FROM jogos WHERE id=%s", (jogo_id_int,))
            jogo = c.fetchone()
            if not jogo:
                conn.close()
                flash("Jogo inválido.", "danger")
                return redirect(url_for("dashboard"))
            
            # Adiciona a seleção principal
            if principal == "A":
                selections.append({"jogo_id": jogo["id"], "tipo": "principal", "escolha": "A", "odd": jogo["odd_a"]})
            elif principal == "X":
                selections.append({"jogo_id": jogo["id"], "tipo": "principal", "escolha": "X", "odd": jogo["odd_x"]})
            elif principal == "B":
                selections.append({"jogo_id": jogo["id"], "tipo": "principal", "escolha": "B", "odd": jogo["odd_b"]})
            
            # Adiciona as seleções extras
            for exid in extras_ids:
                try:
                    exid_int = int(exid)
                except ValueError:
                    continue
                
                c.execute("SELECT * FROM extras WHERE id=%s", (exid_int,))
                row = c.fetchone()
                if row:
                    # Garante que o jogo_id do extra (que pode ser diferente) seja salvo, mas neste caso é o mesmo
                    selections.append({"jogo_id": row["jogo_id"], "tipo": "extra", "escolha": row["descricao"], "odd": row["odd"]})
        
        # --- 2. VALIDAÇÃO E CÁLCULO ---
        if stake <= 0:
            conn.close()
            flash("Valor de aposta precisa ser maior que zero.", "warning")
            return redirect(url_for("dashboard"))

        if not selections:
            conn.close()
            flash("Selecione pelo menos uma aposta.", "warning")
            return redirect(url_for("dashboard"))

        c.execute("SELECT saldo FROM usuarios WHERE id=%s", (usuario_id,))
        user = c.fetchone()
        if not user or user["saldo"] < stake:
            conn.close()
            flash("Saldo insuficiente. Solicite depósito.", "danger")
            return redirect(url_for("dashboard"))

        odd_list = [float(s["odd"]) for s in selections]
        total_odd = calc_total_odd(odd_list)
        potential = calc_potential(stake, total_odd)

        # --- 3. SALVAMENTO NO BANCO ---
        now = datetime.now().isoformat()
        c.execute("INSERT INTO bets (usuario_id, stake, total_odd, potential, status, criado_em) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                  (usuario_id, stake, total_odd, potential, "pendente", now))
        bet_id = c.fetchone()["id"]

        for s in selections:
            # CRUCIAL: O jogo_id está garantido aqui
            c.execute(
    "INSERT INTO bet_selections (bet_id, jogo_id, tipo, escolha, odd, resultado, time_a, time_b, data_hora) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (
        bet_id,
        s.get("jogo_id"),
        s.get("tipo"),
        s.get("escolha"),
        float(s.get("odd")),
        "pendente",
        s.get("time_a"),
        s.get("time_b"),
        str(s.get("data_hora"))
    )
)


        c.execute("UPDATE usuarios SET saldo = saldo - %s WHERE id = %s", (stake, usuario_id))
        conn.commit()
        conn.close()

        flash(f"Aposta registrada. Potencial: R$ {potential:.2f}", "success")
        return redirect(url_for("historico"))

# ------------------ HISTÓRICO / EXIBIR APOSTAS ------------------
# Rota /historico (sem alterações, pois o LEFT JOIN já estava correto)
@app.route("/historico")
def historico():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    uid = session["usuario_id"]
    conn = get_conn()
    c = conn.cursor()

    # pega apostas do usuário
    c.execute("SELECT * FROM bets WHERE usuario_id=%s ORDER BY criado_em DESC", (uid,))
    bets = []
    for b in c.fetchall():
        bdict = row_to_dict(b)

        # pega seleções JUNTANDO info do jogo
        c.execute("""
    SELECT * FROM bet_selections
    WHERE bet_id = %s
    ORDER BY id
""", (b["id"],))

        sels_rows = c.fetchall()

        selections = []
        for s in sels_rows:
            sd = row_to_dict(s)

            # monta descrição legível
            escolha = sd.get("escolha")
            if escolha == "A":
                sd["descricao"] = f"Vitória {sd.get('time_a','Time A')}"
            elif escolha == "B":
                sd["descricao"] = f"Vitória {sd.get('time_b','Time B')}"
            elif escolha == "X":
                sd["descricao"] = "Empate"
            else:
                sd["descricao"] = sd.get("tipo") or "Indefinido"

            # garante resultado
            sd["resultado"] = sd.get("resultado") or "Pendente"

            # garante odd em float
            if sd.get("odd") is not None:
                sd["odd"] = float(sd["odd"])

            selections.append(sd)

        bdict["selections"] = selections
        bets.append(bdict)

    conn.close()
    return render_template("bet_history.html", bets=bets)


# ... (O resto das suas rotas de Depósito/Saque/Admin/Logout estão OK e não precisam de alteração) ...

# ------------------ DEPÓSITO / SAQUE ------------------
@app.route("/depositar", methods=["GET", "POST"])
def depositar():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if request.method == "POST":
        valor = float(request.form.get("valor", 0))
        if valor <= 0:
            flash("Valor inválido.", "warning")
            return redirect(url_for("depositar"))
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO transacoes (usuario_id, tipo, valor, status, criado_em) VALUES (%s,%s,%s,%s,%s)",
                  (session["usuario_id"], "deposito", valor, "pendente", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash("Depósito solicitado. Aguarde aprovação do admin.", "info")
        return redirect(url_for("dashboard"))
    return render_template("depositar.html")

@app.route("/sacar", methods=["GET","POST"])
def sacar():
    if not session.get("usuario_id"):
        return redirect(url_for("login"))
    if request.method == "POST":
        valor = float(request.form.get("valor", 0))
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT saldo FROM usuarios WHERE id=%s", (session["usuario_id"],))
        saldo = c.fetchone()["saldo"]
        if valor <= 0 or valor > saldo:
            conn.close()
            flash("Valor inválido ou saldo insuficiente.", "warning")
            return redirect(url_for("sacar"))
        c.execute("INSERT INTO transacoes (usuario_id, tipo, valor, status, criado_em) VALUES (%s,%s,%s,%s,%s)",
                  (session["usuario_id"], "saque", valor, "pendente", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash("Saque solicitado. Aguarde aprovação do admin.", "info")
        return redirect(url_for("dashboard"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT saldo FROM usuarios WHERE id=%s", (session["usuario_id"],))
    saldo = c.fetchone()["saldo"]
    conn.close()
    return render_template("sacar.html", usuario={"saldo": saldo})


# ------------------ ADMIN GERAL ------------------
@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("usuario_id") or session.get("usuario_nome") != "admin":
        return redirect(url_for("login"))

    conn = get_conn()
    c = conn.cursor()

    # ---------------- Transações Pendentes ----------------
    c.execute("""
        SELECT t.*, u.nome as usuario_nome
        FROM transacoes t
        LEFT JOIN usuarios u ON t.usuario_id = u.id
        ORDER BY t.id DESC
    """)
    transacoes = [row_to_dict(r) for r in c.fetchall()]

    # ---------------- Apostas Pendentes ----------------
    c.execute("""
        SELECT b.*, u.nome AS usuario_nome
        FROM bets b
        JOIN usuarios u ON b.usuario_id = u.id
        WHERE b.status = 'pendente'
        ORDER BY b.id DESC
    """)
    apostas_pendentes = []
    for b in c.fetchall():
        bdict = row_to_dict(b)
        c.execute("""
            SELECT bs.*, j.time_a, j.time_b, j.data_hora
            FROM bet_selections bs
            LEFT JOIN jogos j ON bs.jogo_id = j.id
            WHERE bs.bet_id = %s
            ORDER BY bs.id
        """, (b["id"],))
        sels = []
        for s in c.fetchall():
            sd = row_to_dict(s)
            sd["descricao"] = sd.get("escolha") or "Indefinido"
            dh = sd.get("data_hora")
            if isinstance(dh, datetime):
                sd["data_hora"] = dh.strftime("%d/%m %H:%M")
            sels.append(sd)
        bdict["selections"] = sels
        apostas_pendentes.append(bdict)

    # ---------------- Apostas Finalizadas ----------------
    c.execute("""
        SELECT b.*, u.nome AS usuario_nome
        FROM bets b
        JOIN usuarios u ON b.usuario_id = u.id
        WHERE b.status IN ('ganhou', 'perdeu')
        ORDER BY b.id DESC
    """)
    apostas_finalizadas = []
    for b in c.fetchall():
        bdict = row_to_dict(b)
        c.execute("""
            SELECT bs.*, j.time_a, j.time_b, j.data_hora
            FROM bet_selections bs
            LEFT JOIN jogos j ON bs.jogo_id = j.id
            WHERE bs.bet_id = %s
            ORDER BY bs.id
        """, (b["id"],))
        sels = []
        for s in c.fetchall():
            sd = row_to_dict(s)
            sd["descricao"] = sd.get("escolha") or "Indefinido"
            dh = sd.get("data_hora")
            if isinstance(dh, datetime):
                sd["data_hora"] = dh.strftime("%d/%m %H:%M")
            sels.append(sd)
        bdict["selections"] = sels
        apostas_finalizadas.append(bdict)

    conn.close()
    return render_template(
        "admin_dashboard.html",
        transacoes=transacoes,
        apostas_pendentes=apostas_pendentes,
        apostas_finalizadas=apostas_finalizadas,
    )


@app.route("/admin/approve_transacao/<int:tid>")
def admin_approve_transacao(tid):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM transacoes WHERE id=%s", (tid,))
    t = c.fetchone()
    if not t:
        conn.close()
        flash("Transação não encontrada.", "warning")
        return redirect(url_for("admin_dashboard"))
    if t["status"] != "pendente":
        conn.close()
        flash("Transação já processada.", "info")
        return redirect(url_for("admin_dashboard"))
    if t["tipo"] == "deposito":
        c.execute("UPDATE usuarios SET saldo = saldo + %s WHERE id=%s", (t["valor"], t["usuario_id"]))
    elif t["tipo"] == "saque":
        c.execute("SELECT saldo FROM usuarios WHERE id=%s", (t["usuario_id"],))
        s = c.fetchone()["saldo"]
        if s < t["valor"]:
            c.execute("UPDATE transacoes SET status='reprovado' WHERE id=%s", (tid,))
            conn.commit()
            conn.close()
            flash("Saldo insuficiente — saque reprovado.", "danger")
            return redirect(url_for("admin_dashboard"))
        c.execute("UPDATE usuarios SET saldo = saldo - %s WHERE id=%s", (t["valor"], t["usuario_id"]))
    c.execute("UPDATE transacoes SET status='aprovado' WHERE id=%s", (tid,))
    conn.commit()
    conn.close()
    flash("Transação aprovada.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/reject_transacao/<int:tid>")
def admin_reject_transacao(tid):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE transacoes SET status='reprovado' WHERE id=%s", (tid,))
    conn.commit()
    conn.close()
    flash("Transação reprovada.", "info")
    return redirect(url_for("admin_dashboard"))

# ------------------ ADMIN: gerenciar jogos / extras ------------------
@app.route("/admin_futebol", methods=["GET","POST"])
def admin_futebol():
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    if request.method == "POST":
        time_a = request.form.get("time_a")
        time_b = request.form.get("time_b")
        odd_a = float(request.form.get("odd_a", 1.0))
        odd_x = float(request.form.get("odd_x", 1.0))
        odd_b = float(request.form.get("odd_b", 1.0))
        data_hora = request.form.get("data_hora")
        c.execute("""
            INSERT INTO jogos (time_a, time_b, odd_a, odd_x, odd_b, data_hora, ativo, criado_em) 
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (time_a, time_b, odd_a, odd_x, odd_b, data_hora, 1, datetime.now().isoformat()))
        conn.commit()
        flash("Jogo criado.", "success")
    c.execute("SELECT * FROM jogos ORDER BY data_hora")
    jogos = [row_to_dict(r) for r in c.fetchall()]
    conn.close()
    return render_template("admin_futebol.html", jogos=jogos)

@app.route("/admin_futebol/add_extra/<int:jogo_id>", methods=["POST"])
def admin_add_extra(jogo_id):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    descricao = request.form.get("descricao")
    odd = float(request.form.get("odd", 1.0))
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO extras (jogo_id, descricao, odd, criado_em) VALUES (%s,%s,%s,%s)",
              (jogo_id, descricao, odd, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    flash("Extra adicionado.", "success")
    return redirect(url_for("admin_futebol"))

@app.route("/admin_futebol/delete_extra/<int:extra_id>")
def admin_delete_extra(extra_id):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM extras WHERE id=%s", (extra_id,))
    conn.commit()
    conn.close()
    flash("Extra removido.", "info")
    return redirect(url_for("admin_futebol"))

@app.route("/admin_futebol/delete_game/<int:jogo_id>")
def admin_delete_game(jogo_id):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM jogos WHERE id=%s", (jogo_id,))
    c.execute("DELETE FROM extras WHERE jogo_id=%s", (jogo_id,))
    conn.commit()
    conn.close()
    flash("Jogo removido.", "info")
    return redirect(url_for("admin_futebol"))

# ------------------ ADMIN: resolver aposta ------------------
@app.route("/admin/resolve_bet/<int:bet_id>", methods=["POST"])
def admin_resolve_bet(bet_id):
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    action = request.form.get("action")  # 'ganho' ou 'perdido'
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM bets WHERE id=%s", (bet_id,))
    bet = c.fetchone()
    if not bet:
        conn.close()
        flash("Aposta não encontrada.", "warning")
        return redirect(url_for("admin_dashboard"))
    if bet["status"] != "pendente":
        conn.close()
        flash("Aposta já processada.", "info")
        return redirect(url_for("admin_dashboard"))
    if action == "ganho":
        c.execute("UPDATE usuarios SET saldo = saldo + %s WHERE id=%s", (bet["potential"], bet["usuario_id"]))
        c.execute("UPDATE bets SET status='ganho' WHERE id=%s", (bet_id,))
        flash("Aposta marcada como GANHA e valor creditado ao usuário.", "success")
    else:
        c.execute("UPDATE bets SET status='perdido' WHERE id=%s", (bet_id,))
        flash("Aposta marcada como PERDIDA.", "info")

    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))

# ------------------ ADMIN: limpar histórico ------------------
@app.route("/admin/clear_history", methods=["POST"])
def admin_clear_history():
    if not session.get("is_admin"):
        flash("Acesso negado.", "danger")
        return redirect(url_for("login"))
    conn = get_conn()
    c = conn.cursor()
    # Limpa as apostas e as transações, mas não os jogos
    c.execute("DELETE FROM bet_selections")
    c.execute("DELETE FROM bets")
    c.execute("DELETE FROM transacoes")
    conn.commit()
    conn.close()
    flash("Histórico limpo.", "info")
    return redirect(url_for("admin_dashboard"))

# ------------------ LOGOUT ------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Desconectado.", "info")
    return redirect(url_for("login"))

# ------------------ RODAR ------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)



















