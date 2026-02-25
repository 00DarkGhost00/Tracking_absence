import os, sqlite3
import pandas as pd
import socket
from collections import Counter
from datetime import datetime
from zeroconf import ServiceInfo, Zeroconf
from flask import Flask, render_template, request, redirect, url_for, g, send_file, session, flash, jsonify
from flask import send_file, session, flash 
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'esef_manager_2025'
DATABASE = 'absence_tracker.db'

# ---- AUTO RELOAD APP
app.config['TEMPLATES_AUTO_RELOAD'] = True

# --- AUTH CONFIG ---
USERS = {
    "admin": {"password": "adminEsef2026", "role": "admin"},
    "compta": {"password": "compta2026", "role": "compta"},
    "manager": {"password": "manager2026", "role": "manager"}
}

# --- LOGIN DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTH & LOG OUT ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].lower().strip()
        password = request.form['password']
        
        # Vérification si l'utilisateur existe et si le mot de passe est bon
        if username in USERS and USERS[username]['password'] == password:
            session['logged_in'] = True
            session['username'] = username
            session['role'] = USERS[username]['role'] # On sauvegarde le rôle !
            
            # Redirection intelligente : on envoie chaque rôle vers sa page la plus utile
            if session['role'] == 'compta':
                return redirect(url_for('professors_list')) # Compta va direct aux Heures
            elif session['role'] == 'manager':
                return redirect(url_for('index')) # Manager va direct à la Saisie
            else:
                return redirect(url_for('dashboard')) # Admin va au Dashboard
        else:
            flash('Identifiants incorrects. Veuillez réessayer.', 'danger')
            
    return render_template('login.html')



@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- DATABASE SETUP ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        
        # Initialize Tables
        db.execute("""CREATE TABLE IF NOT EXISTS Professors (
            name TEXT PRIMARY KEY, 
            status TEXT DEFAULT 'Vacataire'
        )""")
        db.execute("CREATE TABLE IF NOT EXISTS Config (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("""CREATE TABLE IF NOT EXISTS AbsenceRecords (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date_absent TEXT, Professeur TEXT, 
            Semestre TEXT, Filiere TEXT, Groupe TEXT, Jour TEXT, Lheure TEXT, Salle TEXT, Module TEXT, absence_reason TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS RattSessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date_ratt TEXT, Professeur TEXT, Lheure TEXT)""")
    return db

@app.teardown_appcontext
def close_connection(e):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

# --- STATS LOGIC ---
def get_stats_for_prof(prof_name):
    db = get_db()
    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    
    start_date = datetime.strptime(s_row['value'], '%Y-%m-%d') if s_row else datetime(2025,10,6)
    end_date = datetime.strptime(e_row['value'], '%Y-%m-%d') if e_row else datetime(2025,12,27)

    schedule = db.execute("SELECT Jour FROM MasterSchedule WHERE Professeur = ?", (prof_name,)).fetchall()
    scheduled_days = [r['Jour'] for r in schedule]
    
    theo_hrs = 0
    if scheduled_days:
        day_map = {0:'Lundi', 1:'Mardi', 2:'Mercredi', 3:'Jeudi', 4:'Vendredi', 5:'Samedi', 6:'Dimanche'}
        current = start_date
        while current <= end_date:
            if day_map[current.weekday()] in scheduled_days:
                theo_hrs += (scheduled_days.count(day_map[current.weekday()]) * 3)
            current += timedelta(days=1)
    
    abs_row = db.execute("SELECT COUNT(*) FROM AbsenceRecords WHERE Professeur = ?", (prof_name,)).fetchone()
    ratt_row = db.execute("SELECT COUNT(*) FROM RattSessions WHERE Professeur = ?", (prof_name,)).fetchone()
    
    abs_h = abs_row[0] * 3 if abs_row else 0
    ratt_h = ratt_row[0] * 3 if ratt_row else 0
    return theo_hrs, abs_h, ratt_h, (theo_hrs - abs_h) + ratt_h

# --- NOUVEAU : FONCTION DE CALCUL DES SÉANCES THEORIQUES (SANS VACANCES) ---
def get_theoretical_sessions_count(db, day_of_week_fr, sem_start_str, sem_end_str):
    """
    Calcule le nombre de séances théoriques en sautant les PÉRIODES de vacances/grèves.
    """
    days_map = {
        "Lundi": 0, "Mardi": 1, "Mercredi": 2, "Jeudi": 3, 
        "Vendredi": 4, "Samedi": 5, "Dimanche": 6
    }
    
    target_weekday = days_map.get(day_of_week_fr.capitalize())
    if target_weekday is None:
        return 0

    try:
        start_date = datetime.strptime(sem_start_str, "%Y-%m-%d")
        end_date = datetime.strptime(sem_end_str, "%Y-%m-%d")
    except:
        return 0

    # 1. Récupérer toutes les PÉRIODES de blocage
    try:
        holidays_data = db.execute("SELECT date_start, date_end FROM Holidays").fetchall()
        blocked_ranges = []
        for h in holidays_data:
            if h['date_start'] and h['date_end']:
                blocked_ranges.append({
                    'start': datetime.strptime(h['date_start'], "%Y-%m-%d"),
                    'end': datetime.strptime(h['date_end'], "%Y-%m-%d")
                })
    except:
        blocked_ranges = []

    count = 0
    current_date = start_date

    # 2. On parcours chaque jour du semestre
    while current_date <= end_date:
        if current_date.weekday() == target_weekday:
            # On vérifie si ce jour tombe PENDANT une période de vacances
            is_blocked = False
            for r in blocked_ranges:
                if r['start'] <= current_date <= r['end']:
                    is_blocked = True
                    break
            
            # Si le jour n'est pas bloqué, on le compte !
            if not is_blocked:
                count += 1
                
        current_date += timedelta(days=1)

    return count


# --- CORE ROUTES ---

@app.route('/')
@login_required
def index():
    db = get_db()
    try: rooms = [r[0] for r in db.execute("SELECT DISTINCT Salle FROM MasterSchedule ORDER BY Salle")]
    except: rooms = []
    slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    return render_template('index.html', rooms=rooms, time_slots=slots, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()

    # 1. KPIs Existants (Prof et Filière)
    top_prof = db.execute("SELECT Professeur, COUNT(*) as c FROM AbsenceRecords GROUP BY Professeur ORDER BY c DESC LIMIT 1").fetchone()
    top_filiere = db.execute("SELECT Filiere, COUNT(*) as c FROM AbsenceRecords GROUP BY Filiere ORDER BY c DESC LIMIT 1").fetchone()
    
    # 2. NOUVEAU KPI : Jour le plus critique (Agrégation par nom du jour)
    all_dates = db.execute("SELECT date_absent FROM AbsenceRecords WHERE date_absent IS NOT NULL AND date_absent != ''").fetchall()
    
    days_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_counts = Counter()
    
    for row in all_dates:
        try:
            # Conversion de la date (ex: '2023-11-15') en objet datetime
            date_obj = datetime.strptime(row['date_absent'], '%Y-%m-%d')
            # Ajout +1 au compteur du jour correspondant
            day_counts[days_fr[date_obj.weekday()]] += 1
        except Exception as e:
            pass # Ignore silencieusement les dates mal formatées
            
    # Récupération du jour vainqueur
    top_day = None
    if day_counts:
        best_day, best_count = day_counts.most_common(1)[0]
        top_day = {'Jour': best_day, 'c': best_count}

    # 3. Statistiques Globales et Taux de Récupération
    total_absences = db.execute("SELECT COUNT(*) FROM AbsenceRecords").fetchone()[0]
    total_rattrapages = db.execute("SELECT COUNT(*) FROM RattSessions").fetchone()[0]
    
    taux_recup = round((total_rattrapages / total_absences * 100)) if total_absences > 0 else 0

    # 4. Absences Récentes
    recent_absences = db.execute("SELECT * FROM AbsenceRecords ORDER BY id DESC LIMIT 20").fetchall()

    return render_template('dashboard.html', 
                           top_prof=top_prof, 
                           top_filiere=top_filiere, 
                           top_day=top_day,
                           total_absences=total_absences,
                           total_rattrapages=total_rattrapages,
                           taux_recup=taux_recup,
                           recent_absences=recent_absences)


# FIX 1: Calcule Theorical Time and Delete Holidays from it 
@app.route('/professors')
@login_required
def professors_list():
    db = get_db()
    
    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    start_str = s_row['value'] if s_row else "2025-10-06"
    end_str = e_row['value'] if e_row else "2025-12-27"

    try:
        all_profs = db.execute('SELECT name, status FROM Professors ORDER BY name').fetchall()
    except Exception as e:
        print(f"Erreur base de données : {e}")
        all_profs = []
    
    prof_list = []
    total_abs_all = 0
    total_ratt_all = 0
    total_theo_all = 0

    for row in all_profs:
        name = row['name']
        full_status = row['status']
        
        schedule = db.execute("SELECT Jour FROM MasterSchedule WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchall()
        scheduled_days = [r['Jour'] for r in schedule]
        
        theo_hrs = 0
        
        # NOUVEAU : Utilisation de la fonction intelligente pour chaque jour enseigné
        if scheduled_days:
            # Compter les occurrences de chaque jour (ex: le prof enseigne 2 fois le Lundi)
            day_counts = Counter(scheduled_days)
            for day, count in day_counts.items():
                # On calcule le nombre réel de lundis ouvrables
                valid_sessions = get_theoretical_sessions_count(db, day, start_str, end_str)
                # On multiplie par le nombre de cours ce jour-là, et par 3 heures
                theo_hrs += (valid_sessions * count * 3)
        
        # --- CALCUL DES ABSENCES ET RATTRAPAGES ---
        # (Le reste de la fonction reste identique)
        abs_count = db.execute("SELECT COUNT(*) FROM AbsenceRecords WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchone()[0]
        abs_h = abs_count * 3
        
        try:
            ratt_count = db.execute("SELECT COUNT(*) FROM RattSessions WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchone()[0]
            ratt_h = ratt_count * 3
        except:
            ratt_h = 0

        realized = (theo_hrs - abs_h) + ratt_h
        
        prof_list.append({
            'name': name,
            'theo': theo_hrs,
            'abs': abs_h,
            'ratt': ratt_h,
            'real': realized,
            'status': full_status
        })
        
        total_theo_all += theo_hrs
        total_abs_all += abs_h
        total_ratt_all += ratt_h

    comp_p = round(((total_theo_all - total_abs_all + total_ratt_all) / total_theo_all * 100)) if total_theo_all > 0 else 0
    abs_p = round((total_abs_all / total_theo_all * 100),2) if total_theo_all > 0 else 0
    ratt_p = round((total_ratt_all / total_theo_all * 100),2) if total_theo_all > 0 else 0

    return render_template('professors.html', 
                           data=prof_list, 
                           comp_perc=comp_p,
                           abs_perc=abs_p,
                           ratt_perc=ratt_p,
                           total_abs=total_abs_all, 
                           total_ratt=total_ratt_all)


# Manage Route 
@app.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_data():
    db = get_db()
    if request.method == 'POST':
        # 1. Update dates
        if 'sem_start' in request.form:
            db.execute("INSERT OR REPLACE INTO Config VALUES ('sem_start', ?)", (request.form['sem_start'],))
            db.execute("INSERT OR REPLACE INTO Config VALUES ('sem_end', ?)", (request.form['sem_end'],))
            db.commit()
            flash("Dates du semestre mises à jour.", "success")
        
        # 2. Upload Schedule File
        if 'file' in request.files and request.files['file'].filename != '':
            f = request.files['file']
            f.save("temp.csv")
            try:
                # Try reading the CSV with a semicolon first
                df = pd.read_csv("temp.csv", sep=';', encoding='utf-8', on_bad_lines='skip')
                
                # Fallback: if 'Professeur' isn't found, try a comma separator and latin-1 encoding
                if 'Professeur' not in df.columns:
                    df = pd.read_csv("temp.csv", sep=',', encoding='latin-1', on_bad_lines='skip')
                
                # Check if the file is valid
                if 'Professeur' not in df.columns:
                    flash("Erreur: Colonne 'Professeur' introuvable. Vérifiez le format de votre CSV.", "danger")
                else:
                    df.columns = [c.replace('FiliÃ©re', 'Filiere').replace('Filiére', 'Filiere').strip() for c in df.columns]
                    df = df.drop_duplicates()
                    
                    conn = sqlite3.connect(DATABASE)
                    df.to_sql('MasterSchedule', conn, if_exists='replace', index=False)
                    
                    # Sync Professors and count them
                    prof_count = 0
                    unique_profs = df['Professeur'].dropna().unique()
                    for p_name in unique_profs:
                        p_clean = str(p_name).strip().upper()
                        cursor = conn.execute("INSERT OR IGNORE INTO Professors (name, status) VALUES (?, 'Vacataire')", (p_clean,))
                        if cursor.rowcount > 0:
                            prof_count += 1
                    conn.commit()
                    conn.close()
                    
                    # Send detailed success message to the HTML
                    flash(f"Succès ! {len(df)} lignes importées dans l'emploi du temps. {prof_count} nouveaux professeurs ajoutés.", "success")
            except Exception as e:
                flash(f"Erreur critique lors de la lecture du fichier : {str(e)}", "danger")
            
            return redirect(url_for('manage_data'))

    # Load UI Data
    try: all_profs = db.execute("SELECT DISTINCT Professeur FROM MasterSchedule ORDER BY Professeur").fetchall()
    except: all_profs = []

    saved_statuses = {row['name']: row['status'] for row in db.execute("SELECT * FROM Professors").fetchall()}
    prof_list = [{'name': p['Professeur'], 'status': saved_statuses.get(p['Professeur'], 'Vacataire')} for p in all_profs]

    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    
    return render_template('manage.html', 
                           s=s_row['value'] if s_row else "2025-10-06", 
                           e=e_row['value'] if e_row else "2025-12-27",
                           professors=prof_list)

@app.route('/prof_status', methods=['GET', 'POST'])
@login_required
def prof_status():
    db = get_db()
    if request.method == 'POST':
        new_prof = request.form.get('prof_name')
        new_status = request.form.get('prof_status')
        if new_prof and new_status:
            new_prof = new_prof.upper().strip() 
            try:
                db.execute("INSERT INTO Professors (name, status) VALUES (?, ?)", (new_prof, new_status))
                db.commit()
                flash(f"Professeur {new_prof} ajouté avec succès.")
            except sqlite3.IntegrityError:
                flash(f"Le professeur {new_prof} existe déjà dans la base.")
        return redirect(url_for('prof_status'))

    try:
        professors = db.execute("SELECT name, status FROM Professors ORDER BY name ASC").fetchall()
    except sqlite3.OperationalError:
        professors = []
    return render_template('prof_status.html', professors=professors)


@app.route('/toggle_status/<name>')
@login_required
def toggle_status(name):
    db = get_db()
    prof = db.execute("SELECT status FROM Professors WHERE name = ?", (name,)).fetchone()
    if prof:
        new_status = "Vacataire" if prof['status'] == "Permanent" else "Permanent"
        db.execute("UPDATE Professors SET status = ? WHERE name = ?", (new_status, name))
        db.commit()
        flash(f"Le statut de {name} a été changé en {new_status}.")
    return redirect(url_for('prof_status'))



# --- NOUVELLE API POUR LES SALLES LIBRES  & Modules ---
# --- API MISE À JOUR : SALLES HABITUELLES + SALLES LIBRES ---
@app.route('/api/available_rooms')
@login_required
def available_rooms():
    db = get_db()
    date_str = request.args.get('date')
    time_slot = request.args.get('time_slot')
    prof = request.args.get('prof', '')
    module = request.args.get('module', '')

    if not date_str or not time_slot:
        return jsonify({'usual': [], 'available': []})

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        day_of_week = days[date_obj.weekday()]

        # 1. Salles habituelles (basées sur ce professeur ET ce module exact)
        usual_rooms = []
        if prof and module:
            u_res = db.execute("SELECT DISTINCT Salle FROM MasterSchedule WHERE Professeur = ? AND Module = ? AND Salle IS NOT NULL AND Salle != ''", (prof, module)).fetchall()
            usual_rooms = [r['Salle'] for r in u_res]

        # 2. Toutes les salles existantes
        all_rooms_query = db.execute("SELECT DISTINCT Salle FROM MasterSchedule WHERE Salle IS NOT NULL AND Salle != ''").fetchall()
        all_rooms = {r['Salle'] for r in all_rooms_query}

        # 3. Salles occupées (Emploi du temps normal)
        occ_ms = db.execute("SELECT Salle FROM MasterSchedule WHERE Jour = ? AND Lheure = ?", (day_of_week, time_slot)).fetchall()
        occupied = {r['Salle'] for r in occ_ms if r['Salle']}
        
        # NOUVEAU : Salles occupées par d'autres RATTRAPAGES ce jour-là !
        occ_ratt = db.execute("SELECT Salle FROM RattSessions WHERE date_ratt = ? AND Lheure = ?", (date_str, time_slot)).fetchall()
        for r in occ_ratt:
            if r['Salle']:
                occupied.add(r['Salle'])

        # 4. Salles libres (Toutes - Occupées)
        available = sorted(list(all_rooms - occupied))
        
        return jsonify({'usual': usual_rooms, 'available': available})
    except Exception as e:
        print("Erreur API Salles:", e)
        return jsonify({'usual': [], 'available': []})
    
# --- 1. MISE À JOUR DE L'API PROF_MODULES ---
@app.route('/api/prof_modules')
@login_required
def prof_modules():
    prof = request.args.get('prof')
    if not prof:
        return jsonify([])
    
    db = get_db()
    try:
        # NOUVEAU : On sélectionne aussi la colonne 'groupe'
        query = """
            SELECT DISTINCT Filiere, Semestre, Module, groupe 
            FROM MasterSchedule 
            WHERE Professeur = ? AND Module IS NOT NULL AND Module != ''
        """
        modules = db.execute(query, (prof,)).fetchall()
        return jsonify([dict(m) for m in modules])
    except Exception as e:
        print("Erreur API Modules:", e)
        return jsonify([])

# --- 2. MISE À JOUR DE PROCESS_RATT ---
@app.route('/process_ratt', methods=['POST'])
@login_required
def process_ratt():
    db = get_db()
    
    # Sécurisation des colonnes
    for col in ['Salle', 'Filiere', 'Semestre', 'Module', 'groupe']:
        try: db.execute(f"ALTER TABLE RattSessions ADD COLUMN {col} TEXT")
        except: pass
        
    # Extraction des données
    prof = request.form['professeur']
    date_ratt = request.form['date']
    time_slot = request.form['time_slot']
    salle = request.form.get('salle', '')
    
    module_data = request.form.get('module_data', '|||')
    parts = module_data.split('|')
    filiere = parts[0] if len(parts) > 0 else ""
    semestre = parts[1] if len(parts) > 1 else ""
    module_name = parts[2] if len(parts) > 2 else ""
    groupe = parts[3] if len(parts) > 3 else ""

    # --- NOUVEAU : ANTI DOUBLE-BOOKING ---
    
    # Vérification 1 : Le professeur a-t-il déjà un rattrapage à cette heure ?
    conflit_prof = db.execute("SELECT * FROM RattSessions WHERE Professeur = ? AND date_ratt = ? AND Lheure = ?", (prof, date_ratt, time_slot)).fetchone()
    if conflit_prof:
        flash(f"Erreur : Le professeur {prof} a déjà un rattrapage programmé le {date_ratt} de {time_slot}.", "danger")
        return redirect(url_for('ratt_session'))

    # Vérification 2 : La salle est-elle déjà prise par un AUTRE rattrapage ?
    if salle:
        conflit_salle = db.execute("SELECT * FROM RattSessions WHERE Salle = ? AND date_ratt = ? AND Lheure = ?", (salle, date_ratt, time_slot)).fetchone()
        if conflit_salle:
            flash(f"Erreur : La salle {salle} est déjà réservée pour un autre rattrapage à ce moment.", "danger")
            return redirect(url_for('ratt_session'))

    # Si tout est OK, on sauvegarde !
    db.execute("""
        INSERT INTO RattSessions 
        (date_ratt, Professeur, Lheure, Salle, Filiere, Semestre, Module, groupe) 
        VALUES (?,?,?,?,?,?,?,?)""", 
        (date_ratt, prof, time_slot, salle, filiere, semestre, module_name, groupe)
    )
    db.commit()
    
    flash("Séance de rattrapage enregistrée avec succès.", "success")
    return redirect(url_for('rattrapages_list'))

# Auto Assign Statue
@app.route('/auto_assign_status', methods=['POST'])
@login_required
def auto_assign_status():
    if 'file' not in request.files:
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for('prof_status'))
        
    file = request.files['file']
    if file.filename == '':
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for('prof_status'))
        
    db = get_db()

    # Assign Permanents from the uploaded CSV
    if file and file.filename.endswith('.csv'):
        content = file.read().decode('utf-8', errors='ignore').splitlines()
        # Clean lines: remove empty ones and the header
        perm_names = [line.strip().upper() for line in content if line.strip() and "PERMANENT" not in line.upper()]
        
        # --- AUTO-CORRECTOR FOR YOUR SPECIFIC FILES ---
        name_corrections = {
            "PR. AYACHI ELSSAS": "PR. EL ISSAS EL AYACHI",
            "PR. EL AYACHI EL ISSAS": "PR. EL ISSAS EL AYACHI",
            "PR. ESSAHABI MARYEM": "PR. ESSAHABI",
            "PR. MEHDIOUI SAKINA": "PR. SAKINA MEHDIOUI",
            "PR. EL FINOU HAMZA": "PR. HAMZA EL FINOU",
            "PR. FASSI FIHRI ZOUBIDA": "PR. ZOUBIDA FASSI FEHRI",
            "PR. JAMAL EDDINE IDRISSI HAKKOUNI": "PR. HAKOUNI JAMAL"
        }
        
        # Reset everyone to Vacataire before applying the new Permanents list
        db.execute("UPDATE Professors SET status = 'Vacataire'")
        
        count = 0
        for original_name in perm_names:
            # 1. Vérifier si le nom a besoin d'être corrigé
            name_to_update = name_corrections.get(original_name, original_name)
            
            # 2. Mettre à jour le statut du professeur
            cursor = db.execute("UPDATE Professors SET status = 'Permanent' WHERE UPPER(TRIM(name)) = ?", (name_to_update,))
            
            # 3. Si le prof n'existe pas du tout (ex: PR. ELAOUFIR YASMINA qui a 0h), on le crée !
            if cursor.rowcount == 0:
                db.execute("INSERT INTO Professors (name, status) VALUES (?, 'Permanent')", (name_to_update,))
            
            count += 1
                
        db.commit()
        flash(f"Succès total : {count} professeurs permanents ont été synchronisés ! (Noms corrigés automatiquement)", "success")
    else:
        flash("Veuillez uploader un fichier CSV valide.", "danger")
        
    return redirect(url_for('prof_status'))

@app.route('/export_db')
@login_required
def export_db():
    return send_file(DATABASE, as_attachment=True, download_name=f"backup_{datetime.now().strftime('%Y-%m-%d')}.db")

@app.route('/restore_db', methods=['POST'])
@login_required
def restore_db():
    if 'backup_file' in request.files:
        file = request.files['backup_file']
        if file.filename.endswith('.db'):
            db = getattr(g, '_database', None)
            if db: db.close()
            file.save(DATABASE)
            return redirect(url_for('manage_data'))
    return "Invalid file", 400

@app.route('/process_absence', methods=['POST'])
@login_required
def process_absence():
    db = get_db()
    date_str = request.form.get('date')
    time_slot = request.form.get('time_slot')
    empty_rooms = request.form.getlist('empty_rooms')

    if not date_str or not time_slot or not empty_rooms:
        flash("Veuillez remplir tous les champs et sélectionner au moins une salle.", "warning")
        return redirect(url_for('index')) 

    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_of_week = days[date_obj.weekday()]

    count = 0
    for room in empty_rooms:
        schedule_entries = db.execute('''
            SELECT Professeur, Semestre, Filiere, Groupe, Module 
            FROM MasterSchedule 
            WHERE Jour = ? AND Lheure = ? AND Salle = ?
        ''', (day_of_week, time_slot, room)).fetchall()

        for entry in schedule_entries:
            existing = db.execute('''
                SELECT id FROM AbsenceRecords 
                WHERE date_absent = ? AND Lheure = ? AND Salle = ? AND Professeur = ?
            ''', (date_str, time_slot, room, entry['Professeur'])).fetchone()

            if not existing:
                db.execute('''
                    INSERT INTO AbsenceRecords 
                    (date_absent, Professeur, Semestre, Filiere, Groupe, Jour, Lheure, Salle, Module, absence_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (date_str, entry['Professeur'], entry['Semestre'], entry['Filiere'], 
                      entry['Groupe'], day_of_week, time_slot, room, entry['Module'], 'Non justifiée'))
                count += 1

    db.commit()
    flash(f"{count} absence(s) enregistrée(s) avec succès.", "success")
    return redirect(url_for('dashboard'))

@app.route('/delete_absence/<int:absence_id>', methods=['POST'])
@login_required
def delete_absence(absence_id):
    db = get_db()
    db.execute("DELETE FROM AbsenceRecords WHERE id=?", (absence_id,))
    db.commit()
    flash("Absence supprimée avec succès.", "info")
    return redirect(url_for('dashboard'))

@app.route('/ratt_session')
@login_required
def ratt_session():
    db = get_db()
    try: profs = db.execute("SELECT DISTINCT Professeur FROM MasterSchedule ORDER BY Professeur").fetchall()
    except: profs = []
    return render_template('ratt_session.html', professors=profs, time_slots=["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"], today=datetime.now().strftime('%Y-%m-%d'))


# Route Emplois de Temps
@app.route('/schedule', methods=['GET'])
@login_required
def view_schedule():
    db = get_db()
    
    # 1. Récupérer les options pour TOUS les menus déroulants
    try:
        filieres = [f['Filiere'] for f in db.execute("SELECT DISTINCT Filiere FROM MasterSchedule WHERE Filiere != '' ORDER BY Filiere").fetchall()]
        semestres = [s['Semestre'] for s in db.execute("SELECT DISTINCT Semestre FROM MasterSchedule WHERE Semestre != '' ORDER BY Semestre").fetchall()]
        groupes = [g['groupe'] for g in db.execute("SELECT DISTINCT groupe FROM MasterSchedule WHERE groupe != '' ORDER BY groupe").fetchall()]
        
        # NOUVEAU : Professeurs et Modules
        professeurs = [p['Professeur'] for p in db.execute("SELECT DISTINCT Professeur FROM MasterSchedule WHERE Professeur != '' ORDER BY Professeur").fetchall()]
        modules = [m['Module'] for m in db.execute("SELECT DISTINCT Module FROM MasterSchedule WHERE Module != '' ORDER BY Module").fetchall()]
    except:
        filieres, semestres, groupes, professeurs, modules = [], [], [], [], []

    # 2. Récupérer le type de recherche et les choix
    search_type = request.args.get('search_type', 'classe') # 'classe', 'prof' ou 'module'
    
    selected_filiere = request.args.get('filiere', '')
    selected_semestre = request.args.get('semestre', '')
    selected_groupe = request.args.get('groupe', 'ALL')
    selected_prof = request.args.get('professeur', '')
    selected_module = request.args.get('module', '')
    
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    time_slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00",]
    
    grid = {h: {j: [] for j in jours} for h in time_slots}
    has_data = False
    schedule_title = ""

    # 3. Remplir la grille selon le type de recherche
    if search_type == 'classe' and selected_filiere and selected_semestre:
        query = "SELECT Jour, Lheure, Professeur, Module, Salle, groupe FROM MasterSchedule WHERE Filiere = ? AND Semestre = ?"
        params = [selected_filiere, selected_semestre]
        if selected_groupe != 'ALL':
            query += " AND groupe = ?"
            params.append(selected_groupe)
        schedule_data = db.execute(query, params).fetchall()
        grp_text = f" - Groupe {selected_groupe}" if selected_groupe != 'ALL' else " - Vue Globale"
        schedule_title = f"{selected_filiere} (S{selected_semestre}){grp_text}"
        
    elif search_type == 'prof' and selected_prof:
        query = "SELECT Jour, Lheure, Filiere, Semestre, Module, Salle, groupe FROM MasterSchedule WHERE Professeur = ?"
        schedule_data = db.execute(query, [selected_prof]).fetchall()
        schedule_title = f"Emploi du temps : {selected_prof}"
        
    elif search_type == 'module' and selected_module:
        query = "SELECT Jour, Lheure, Professeur, Filiere, Semestre, Salle, groupe FROM MasterSchedule WHERE Module = ?"
        schedule_data = db.execute(query, [selected_module]).fetchall()
        schedule_title = f"Module : {selected_module}"
        
    else:
        schedule_data = []

    # Remplissage de la matrice
    for row in schedule_data:
        j = row['Jour'].capitalize().strip()
        h = row['Lheure'].strip()
        if h in grid and j in grid[h]:
            grid[h][j].append(row)
            has_data = True

    return render_template('schedule.html', 
                           filieres=filieres, semestres=semestres, groupes=groupes,
                           professeurs=professeurs, modules=modules,
                           search_type=search_type,
                           selected_filiere=selected_filiere, selected_semestre=selected_semestre, selected_groupe=selected_groupe,
                           selected_prof=selected_prof, selected_module=selected_module,
                           jours=jours, time_slots=time_slots, grid=grid, has_data=has_data, schedule_title=schedule_title)

# --- GESTION DES Emplois de Temps ---
@app.route('/add_schedule', methods=['POST'])
@login_required
def add_schedule():
    db = get_db()
    
    # Récupération des données du modal
    jour = request.form.get('jour')
    heure = request.form.get('heure')
    prof = request.form.get('prof', '').strip().upper()
    module = request.form.get('module', '').strip()
    salle = request.form.get('salle', '').strip()
    filiere = request.form.get('filiere', '').strip()
    semestre = request.form.get('semestre', '').strip()
    groupe = request.form.get('groupe', '').strip()

    if jour and heure and prof and filiere and semestre:
        db.execute("""
            INSERT INTO MasterSchedule (Jour, Lheure, Professeur, Module, Salle, Filiere, Semestre, groupe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (jour, heure, prof, module, salle, filiere, semestre, groupe))
        db.commit()
        flash(f"Nouvelle séance ajoutée pour {prof} le {jour} à {heure}.", "success")
    else:
        flash("Erreur : Veuillez remplir les champs obligatoires (Filière, Semestre, Professeur).", "danger")
        
    # Magie : request.referrer permet de recharger la page exactement là où vous étiez !
    return redirect(request.referrer or url_for('view_schedule'))

@app.route('/edit_schedule', methods=['POST'])
@login_required
def edit_schedule():
    db = get_db()
    slot_id = request.form.get('slot_id')
    new_prof = request.form.get('new_prof')
    new_module = request.form.get('new_module')
    
    if slot_id and new_prof:
        # On met à jour l'emploi du temps principal avec les bons noms de colonnes
        db.execute("""
            UPDATE MasterSchedule 
            SET Professeur = ?, Module = ?
            WHERE rowid = ?
        """, (new_prof.strip().upper(), new_module, slot_id))
        db.commit()
        flash(f"La séance a été modifiée avec succès. Nouveau professeur : {new_prof}.", "success")
    else:
        flash("Erreur lors de la modification de la séance.", "danger")
        
    return redirect(url_for('view_schedule'))

# --- GESTION DES JOURS EXCEPTIONNELS (VACANCES, GRÈVES, FÉRIÉS) ---

@app.route('/holidays', methods=['GET', 'POST'])
@login_required
def manage_holidays():
    db = get_db()
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS Holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_start TEXT,
            date_end TEXT,
            description TEXT,
            type_holiday TEXT
        )
    """)
    
    for col in ['date_start', 'date_end', 'description', 'type_holiday']:
        try: db.execute(f"ALTER TABLE Holidays ADD COLUMN {col} TEXT")
        except: pass
    db.commit()

    if request.method == 'POST':
        d_start = request.form.get('date_start')
        d_end = request.form.get('date_end')
        h_desc = request.form.get('description')
        h_type = request.form.get('type_holiday')
        
        if not d_end:
            d_end = d_start
            
        if d_start and h_desc:
            if d_start <= d_end:
                db.execute("INSERT INTO Holidays (date_start, date_end, description, type_holiday) VALUES (?, ?, ?, ?)", 
                           (d_start, d_end, h_desc, h_type))
                db.commit()
                flash("Période exceptionnelle ajoutée avec succès.", "success")
            else:
                flash("Erreur : La date de fin doit être après la date de début.", "danger")
        
        return redirect(url_for('manage_holidays'))

    # CORRECTION ICI : On force SQLite à nous donner son identifiant caché "rowid" sous le nom "id"
    holidays = db.execute("SELECT rowid as id, * FROM Holidays ORDER BY date_start ASC").fetchall()
    return render_template('holidays.html', holidays=holidays)

# Supprimé la liste des jours fériés triée par date
@app.route('/delete_holiday/<int:h_id>', methods=['POST'])
@login_required
def delete_holiday(h_id):
    db = get_db()
    # CORRECTION ICI : On supprime la ligne en utilisant le fameux "rowid" caché
    db.execute("DELETE FROM Holidays WHERE rowid = ?", (h_id,))
    db.commit()
    flash("Période exceptionnelle supprimée.", "success")
    return redirect(url_for('manage_holidays'))


# Delete Ratt Route

@app.route('/delete_ratt/<int:ratt_id>', methods=['POST'])
@login_required
def delete_ratt(ratt_id):
    db = get_db()
    try:
        db.execute("DELETE FROM RattSessions WHERE id = ?", (ratt_id,))
        db.commit()
        flash("Séance de rattrapage supprimée avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de la suppression : {e}", "danger")
        
    # Redirige vers la page précédente (soit la liste globale, soit les détails du prof)
    return redirect(request.referrer or url_for('rattrapages_list'))


# Get Prof Details
@app.route('/professor/<path:prof_name>')
@login_required
def professor_details(prof_name):
    db = get_db()
    clean_name = prof_name.upper().strip()

    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    start_str = s_row['value'] if s_row else "2025-10-06"
    end_str = e_row['value'] if e_row else "2025-12-27"

    prof_data = db.execute("SELECT status FROM Professors WHERE UPPER(TRIM(name)) = ?", (clean_name,)).fetchone()
    status = prof_data['status'] if prof_data else "Vacataire"

    schedule = db.execute("SELECT Jour FROM MasterSchedule WHERE UPPER(TRIM(Professeur)) = ?", (clean_name,)).fetchall()
    scheduled_days = [r['Jour'] for r in schedule]
    
    theo_hrs = 0
    
    # NOUVEAU : Utilisation de la fonction intelligente
    if scheduled_days:
        day_counts = Counter(scheduled_days)
        for day, count in day_counts.items():
            valid_sessions = get_theoretical_sessions_count(db, day, start_str, end_str)
            theo_hrs += (valid_sessions * count * 3)

    absences = db.execute("SELECT * FROM AbsenceRecords WHERE UPPER(TRIM(Professeur)) = ? ORDER BY id DESC", (clean_name,)).fetchall()
    rattrapages = db.execute("SELECT * FROM RattSessions WHERE UPPER(TRIM(Professeur)) = ? ORDER BY date_ratt DESC", (clean_name,)).fetchall()

    abs_h = len(absences) * 3
    ratt_h = len(rattrapages) * 3
    real = (theo_hrs - abs_h) + ratt_h

    return render_template('professor_details.html', 
                           prof_name=prof_name, 
                           status=status,
                           theo=theo_hrs, 
                           abs_h=abs_h, 
                           ratt_h=ratt_h, 
                           real=real, 
                           absences=absences, 
                           rattrapages=rattrapages, 
                           sem_start=start_str, 
                           sem_end=end_str)


# Get Ratt Liste"
@app.route('/rattrapages')
@login_required
def rattrapages_list():
    db = get_db()
    rattrapages = db.execute("SELECT * FROM RattSessions ORDER BY date_ratt DESC").fetchall()
    return render_template('rattrapages.html', rattrapages=rattrapages)

# FIX 8: Ensures the Professors table is correctly cleared when you click the danger button
# Cherchez cette fonction et ajoutez la ligne concernant "Holidays"
@app.route('/reset_semester', methods=['POST'])
@login_required
def reset_semester():
    db = get_db()
    db.execute("DELETE FROM AbsenceRecords")
    db.execute("DELETE FROM RattSessions")
    db.execute("DELETE FROM MasterSchedule")
    
    # NOUVEAU : Vider aussi le calendrier des jours exceptionnels
    try:
        db.execute("DELETE FROM Holidays")
    except:
        pass # Au cas où la table n'a pas encore été créée
        
    db.commit()
    flash("Le semestre a été entièrement réinitialisé.", "success")
    return redirect(url_for('settings'))


# FIX 9: The networking code at the end is completed safely
if __name__ == '__main__':
    # L'astuce os.environ permet d'éviter le crash "NonUniqueNameException"
    # en empêchant Zeroconf de se lancer en double à cause du mode debug=True de Flask.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        
        info = ServiceInfo("_http._tcp.local.", "tracker._http._tcp.local.", addresses=[socket.inet_aton(local_ip)], port=80, server="tracker.local.")
        zeroconf = Zeroconf()
        zeroconf.register_service(info)
        
        try: 
            app.run(host='0.0.0.0', port=80, debug=True)
        finally: 
            zeroconf.unregister_service(info)
            zeroconf.close()
    else:
        # Lancement normal (le processus parent)
        app.run(host='0.0.0.0', port=80, debug=True)
