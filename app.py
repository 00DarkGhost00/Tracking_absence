import os, sqlite3
import pandas as pd
import socket
import io
from collections import Counter
from zeroconf import ServiceInfo, Zeroconf
from flask import Flask, render_template, request, redirect, url_for, g, send_file, session, flash, jsonify
from flask import send_file, session, flash 
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import locale

app = Flask(__name__)
app.config['SECRET_KEY'] = 'esef_manager_2025'
DATABASE = 'absence_tracker.db'

# ---- AUTO RELOAD APP
app.config['TEMPLATES_AUTO_RELOAD'] = True

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
        
        db = get_db()
        user = db.execute("SELECT * FROM Users WHERE username = ?", (username,)).fetchone()
        
        # Correction ici : on utilise check_password_hash
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            
            # Redirection intelligente
            if session['role'] == 'compta': 
                return redirect(url_for('professors_list'))
            elif session['role'] == 'manager': 
                return redirect(url_for('index'))
            else: 
                return redirect(url_for('dashboard'))
        else:
            flash('Identifiants incorrects.', 'danger')
            
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))



# --- DATABASE SETUP ---

def init_db():
    db = get_db()
    # Table des Utilisateurs
    db.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL,
            email TEXT
        )
    ''')

    try:
        db.execute("ALTER TABLE Users ADD COLUMN email TEXT")
        db.commit()
    except:
        pass # La colonne existe déjà, on ne fait rien
    
    # Liste des utilisateurs par défaut à créer
    default_users = [
        ('admin', 'adminEsef2026', 'Administrateur Système', 'admin'),
        ('compta', 'compta2026', 'Service Comptabilité', 'compta'),
        ('manager', 'manager2026', 'Manager Scolarité', 'manager')
    ]

    for username, password, full_name, role in default_users:
        user_exists = db.execute("SELECT 1 FROM Users WHERE username = ?", (username,)).fetchone()
        if not user_exists:
            hashed_pw = generate_password_hash(password)
            db.execute("INSERT INTO Users (username, password, full_name, role) VALUES (?, ?, ?, ?)",
                       (username, hashed_pw, full_name, role))
    
    db.commit()
    
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


# Creation des utilisateurs par défaut
@app.route('/admin/utilisateurs', methods=['GET', 'POST'])
@login_required
def manage_users():
    # Sécurité : Seul le rôle 'admin' peut voir cette page
    if session.get('role') != 'admin':
        flash("Accès interdit : Réservé à l'administrateur.", "danger")
        return redirect(url_for('dashboard'))

    db = get_db()
    if request.method == 'POST':
        username = request.form.get('username').lower().strip()
        password = request.form.get('password')
        role = request.form.get('role')
        email = request.form.get('email')
        full_name = request.form.get('full_name')

        try:
            hashed_pw = generate_password_hash(password)
            db.execute("INSERT INTO Users (username, password, full_name, role, email) VALUES (?, ?, ?, ?, ?)",
                       (username, hashed_pw, full_name, role, email))
            db.commit()
            flash(f"L'utilisateur {username} a été créé !", "success")
        except:
            flash("Erreur : Ce nom d'utilisateur existe déjà.", "danger")

    users = db.execute("SELECT id, username, full_name, role, email FROM Users").fetchall()
    return render_template('manage_users.html', users=users)

# --- SUPPRIMER UN UTILISATEUR ---
@app.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('dashboard'))
    
    db = get_db()
    # On empêche l'admin de se supprimer lui-même par erreur
    if user_id == session.get('user_id'):
        flash("Action impossible : Vous ne pouvez pas supprimer votre propre compte.", "danger")
        return redirect(url_for('manage_users'))
        
    db.execute("DELETE FROM Users WHERE id = ?", (user_id,))
    db.commit()
    log_activity('SUPPRESSION', 'Sécurité', f"Utilisateur  {user_id} supprimé")
    flash("Utilisateur supprimé avec succès.", "success")
    return redirect(url_for('manage_users'))

# --- MODIFIER UN UTILISATEUR (Email, Rôle ou Password) ---
@app.route('/admin/update_user/<int:user_id>', methods=['POST'])
@login_required
def update_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('dashboard'))
    
    db = get_db()
    new_email = request.form.get('email')
    new_password = request.form.get('password')
    new_role = request.form.get('role') # Nouveau champ récupéré
    
    # Mise à jour de l'email et du rôle
    db.execute("UPDATE Users SET email = ?, role = ? WHERE id = ?", (new_email, new_role, user_id))
    
    # Si un mot de passe a été saisi, on le hache et on l'enregistre
    if new_password and len(new_password) > 0:
        hashed_pw = generate_password_hash(new_password)
        db.execute("UPDATE Users SET password = ? WHERE id = ?", (hashed_pw, user_id))
        flash("Email, Rôle et Mot de passe mis à jour.", "success")
    else:
        flash("Email et Rôle mis à jour.", "info")

    log_activity('MODIFICATION', 'Sécurité', f"Utilisateur {user_id} mis à jour (Email/Rôle/Mot de passe)")    
    db.commit()
    return redirect(url_for('manage_users'))


# =======================================================
# GESTION DES DONNÉES DE BASE (LE COEUR DE L'APPLICATION)
# =======================================================

def init_core_tables():
    db = get_db()
    db.execute("CREATE TABLE IF NOT EXISTS Filieres (nom TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE IF NOT EXISTS Semestres (nom TEXT PRIMARY KEY)")
    # Modification : La table Modules a maintenant filiere et semestre
    db.execute("""CREATE TABLE IF NOT EXISTS Modules (
                  nom TEXT PRIMARY KEY,
                  filiere TEXT,
                  semestre TEXT)""")
    db.execute("CREATE TABLE IF NOT EXISTS Groupes (nom TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE IF NOT EXISTS Professors (name TEXT PRIMARY KEY, status TEXT DEFAULT 'Vacataire')")
    db.commit()
    
    # MIGRATION : Si la table Modules existait déjà sans les colonnes, on les ajoute
    try:
        db.execute("ALTER TABLE Modules ADD COLUMN filiere TEXT")
        db.execute("ALTER TABLE Modules ADD COLUMN semestre TEXT")
        db.commit()
    except:
        pass # Les colonnes existent déjà


# Route pour gérer les données de base (Filières, Semestres, Modules, Groupes, Professeurs)
@app.route('/donnees')
@login_required
def manage_donnees():
    init_core_tables() # S'assure que les nouvelles colonnes existent
    db = get_db()
    
    filieres = db.execute("SELECT nom FROM Filieres ORDER BY nom").fetchall()
    semestres = db.execute("SELECT nom FROM Semestres ORDER BY nom").fetchall()
    
    # On récupère maintenant TOUTES les informations du module
    modules = db.execute("SELECT nom, filiere, semestre FROM Modules ORDER BY nom").fetchall()
    
    groupes = db.execute("SELECT nom FROM Groupes ORDER BY nom").fetchall()
    professeurs = db.execute("SELECT name, status FROM Professors ORDER BY name").fetchall()
    
    return render_template('donnees.html', 
                           filieres=filieres, 
                           semestres=semestres, 
                           modules=modules, 
                           groupes=groupes, 
                           professeurs=professeurs)



#   Route pour ajouter une nouvelle donnée (Filière, Semestre, Module, Groupe, Professeur)
@app.route('/add_donnee', methods=['POST'])
@login_required
def add_donnee():
    db = get_db()
    type_donnee = request.form.get('type')
    valeur = request.form.get('valeur', '').strip()
    status = request.form.get('status', 'Vacataire') # Pour profs
    
    # Nouveaux champs pour les modules
    filiere = request.form.get('filiere')
    semestre = request.form.get('semestre')

    if not valeur:
        flash("La valeur ne peut pas être vide.", "warning")
        return redirect(url_for('manage_donnees'))

    try:
        if type_donnee == 'Filiere': 
            db.execute("INSERT INTO Filieres (nom) VALUES (?)", (valeur,))
        elif type_donnee == 'Semestre': 
            db.execute("INSERT INTO Semestres (nom) VALUES (?)", (valeur,))
        elif type_donnee == 'Module': 
            # On enregistre le module AVEC sa filière et son semestre
            db.execute("INSERT INTO Modules (nom, filiere, semestre) VALUES (?, ?, ?)", (valeur, filiere, semestre))
        elif type_donnee == 'Groupe': 
            db.execute("INSERT INTO Groupes (nom) VALUES (?)", (valeur,))
        elif type_donnee == 'Professeur': 
            db.execute("INSERT INTO Professors (name, status) VALUES (?, ?)", (valeur, status))


        # --- LOG ---
        log_activity('AJOUT', 'Données de Base', f"Ajout de '{valeur}' à la catégorie {type_donnee} par {session.get('username', 'Admin')}")
        # ---- -----
        db.commit()
        flash(f"{type_donnee} ajouté avec succès.", "success")
    except sqlite3.IntegrityError:
        flash(f"Cette valeur existe déjà.", "danger")
    except Exception as e:
        flash(f"Erreur : {str(e)}", "danger")

    return redirect(url_for('manage_donnees')) # Modifiez si votre route a un autre nom
    
# Route pour supprimer une donnée (Filière, Semestre, Module, Groupe, Professeur)
@app.route('/delete_donnee/<type_donnee>/<valeur>', methods=['POST'])
@login_required
def delete_donnee(type_donnee, valeur):
    # Sécurité Admin
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))

    db = get_db()
    try:
        if type_donnee == 'Filiere': 
            db.execute("DELETE FROM Filieres WHERE nom = ?", (valeur,))
            # Optionnel : Mettre à NULL les modules liés à cette filière si on la supprime
            # db.execute("UPDATE Modules SET filiere = NULL WHERE filiere = ?", (valeur,))
            
        elif type_donnee == 'Semestre': 
            db.execute("DELETE FROM Semestres WHERE nom = ?", (valeur,))
            
        elif type_donnee == 'Module': 
            db.execute("DELETE FROM Modules WHERE nom = ?", (valeur,))
            
        elif type_donnee == 'Groupe': 
            db.execute("DELETE FROM Groupes WHERE nom = ?", (valeur,))
            
        elif type_donnee == 'Professeur': 
            db.execute("DELETE FROM Professors WHERE name = ?", (valeur,))
            
        db.commit()
        
        # --- LOG ---
        username = session.get('username', 'Admin')
        log_activity('SUPPRESSION', 'Données de Base', f"Suppression de '{valeur}' de la catégorie {type_donnee} par {username}")
        # -----------
        
        flash(f"{valeur} a été retiré des {type_donnee}s.", "success")
    except Exception as e:
        flash(f"Erreur lors de la suppression: {str(e)}", "danger")
    
    return redirect(url_for('manage_donnees'))


# ==========================================
# SYSTÈME DE LOGS (JOURNAL D'ACTIVITÉS)
# ==========================================
def init_log_table():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS ActivityLogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            user_name TEXT,  /* NOUVELLE COLONNE POUR L'UTILISATEUR */
            action_type TEXT,
            entity_type TEXT,
            description TEXT
        )
    """)
    # On s'assure que la colonne existe si la table était déjà créée
    try:
        db.execute("ALTER TABLE ActivityLogs ADD COLUMN user_name TEXT DEFAULT 'Système'")
    except:
        pass
    db.commit()

def log_activity(action_type, entity_type, description):
    init_log_table()
    db = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # On récupère le nom de l'utilisateur connecté (modifiez 'username' si vous utilisez une autre clé de session)
    try:
        utilisateur_actuel = session.get('username', 'Admin') # Ou current_user.username si vous utilisez Flask-Login
    except:
        utilisateur_actuel = "Système"

    db.execute("INSERT INTO ActivityLogs (timestamp, user_name, action_type, entity_type, description) VALUES (?, ?, ?, ?, ?)",
               (now, utilisateur_actuel, action_type.upper(), entity_type, description))
    db.commit()

@app.route('/logs')
@login_required
def view_logs():
    init_log_table()
    db = get_db()
    # On récupère les 500 dernières actions
    logs = db.execute("SELECT * FROM ActivityLogs ORDER BY timestamp DESC LIMIT 500").fetchall()
    return render_template('logs.html', logs=logs)

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


try:
    locale.setlocale(locale.LC_TIME, "fr_FR.utf8") # Pour Linux/Mac
except:
    try:
        locale.setlocale(locale.LC_TIME, "French_France.1252") # Pour Windows
    except:
        pass # Garde la langue par défaut si échec

# Export Liste Professeurs (Excel)
@app.route('/export_professors')
@login_required
def export_professors():
    db = get_db()
    
    # Sécurisation de la casse (majuscules/minuscules)
    user_role = session.get('role', '').lower()

    # BARRIÈRE 1: Vérification du Rôle (admin ou compta)
    if user_role not in ['admin', 'compta']:
        flash("Vous n'avez pas l'autorisation d'exporter ces données.", "danger")
        return redirect(url_for('professors_list'))
    
    # BARRIÈRE 2: Vérification si l'Admin a autorisé l'export
    status = db.execute("SELECT value FROM Config WHERE key='export_visibility'").fetchone()
    # Si on est 'compta' et que c'est masqué, on interdit l'accès
    if user_role == 'compta' and (not status or status['value'] == 'hidden'):
        flash("L'exportation est actuellement désactivée par l'administrateur.", "warning")
        return redirect(url_for('professors_list'))
    
    # 1. Récupérer les dates du semestre pour le calcul théorique
    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    start_str = s_row['value'] if s_row else "2025-10-06"
    end_str = e_row['value'] if e_row else "2025-12-27"

    # 2. Récupérer tous les professeurs
    all_profs = db.execute('SELECT name, status FROM Professors ORDER BY name').fetchall()
    
    export_data = []

    for row in all_profs:
        name = row['name']
        status = row['status']
        
        # Calcul des heures théoriques
        schedule = db.execute("SELECT Jour FROM MasterSchedule WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchall()
        scheduled_days = [r['Jour'] for r in schedule]
        
        theo_hrs = 0
        if scheduled_days:
            day_counts = Counter(scheduled_days)
            for day, count in day_counts.items():
                valid_sessions = get_theoretical_sessions_count(db, day, start_str, end_str)
                theo_hrs += (valid_sessions * count * 3)
        
        # Calcul des absences
        abs_count = db.execute("SELECT COUNT(*) FROM AbsenceRecords WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchone()[0]
        abs_h = abs_count * 3
        
        # Calcul des rattrapages
        try:
            ratt_count = db.execute("SELECT COUNT(*) FROM RattSessions WHERE UPPER(TRIM(Professeur)) = ?", (name,)).fetchone()[0]
            ratt_h = ratt_count * 3
        except:
            ratt_h = 0

        # Calcul du total réalisé
        realized = (theo_hrs - abs_h) + ratt_h
       
        
        # Ajouter les données à la liste d'export
        export_data.append({
            'Nom du Professeur': name,
            'Statut': status,
            'Heures Théoriques': theo_hrs,
            'Heures Absences': abs_h,
            'Heures Rattrapages': ratt_h,
            'Heures Réalisées': realized,

            'Période': f"{start_str} au {end_str}"
        })
   
    # 3. Création du fichier Excel
    df = pd.DataFrame(export_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='Esef _ ERP') as writer:
        df.to_excel(writer, index=False, sheet_name='Suivi Professeurs')
    
    output.seek(0)
    
    # 4. ENREGISTREMENT DANS LES LOGS D'ACTIVITÉ
    username = session.get('username', 'Inconnu')
    log_activity('EXPORT', 'Base de données', f"Exportation Excel du suivi des professeurs par {username}.")
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"Rapport_Complet_Professeurs_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    )

# --- FILTRE JINJA2 POUR AFFICHER LE NOM DU JOUR EN FRANÇAIS ---
@app.template_filter('get_day_name')
def get_day_name_filter(date_str):
    """ Transforme une date 'YYYY-MM-DD' en nom de jour 'Lundi' """
    if not date_str:
        return ""
    try:
        # On transforme la chaîne en objet date
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        # On récupère le nom du jour (ex: Lundi)
        return date_obj.strftime('%A').capitalize()
    except Exception:
        return date_str # Retourne la date brute en cas d'erreur


# --- CORE ROUTES ---

@app.route('/')
@login_required
def index():
    db = get_db()
    try: rooms = [r[0] for r in db.execute("SELECT DISTINCT Salle FROM MasterSchedule ORDER BY Salle")]
    except: rooms = []
    slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    return render_template('index.html', rooms=rooms, time_slots=slots, today=datetime.now().strftime('%Y-%m-%d'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = get_db()
    user_id = session.get('user_id')

    if request.method == 'POST':
        full_name = request.form.get('full_name')
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Mise à jour du nom
        db.execute("UPDATE Users SET full_name = ? WHERE id = ?", (full_name, user_id))
        
        # Changement de mot de passe si rempli
        if new_password:
            if new_password == confirm_password:
                hashed_pw = generate_password_hash(new_password)
                db.execute("UPDATE Users SET password = ? WHERE id = ?", (hashed_pw, user_id))
                flash("Profil et mot de passe mis à jour !", "success")
            else:
                flash("Les mots de passe ne correspondent pas.", "danger")
        else:
            flash("Profil mis à jour.", "info")
        
        db.commit()
        session['full_name'] = full_name # Rafraîchir la session

    user = db.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    return render_template('profile.html', user=user)



# DASHBOARD AVEC NOUVEAU KPI : JOUR LE PLUS CRITIQUE (LE PLUS D'ABSENCES)
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
    recent_absences = db.execute('''
                    SELECT * FROM AbsenceRecords ORDER BY date_absent DESC, Lheure DESC
        LIMIT 500''').fetchall()

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

    # --- AJOUTEZ CES LIGNES ICI ---
    # Récupérer le statut de l'export dans la table Config
    res = db.execute("SELECT value FROM Config WHERE key='export_visibility'").fetchone()
    export_status = res['value'] if res else 'hidden'
    # ------------------------------
    
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
                           total_ratt=total_ratt_all,
                           export_status=export_status)


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
            log_activity('CONFIGURATION', 'Système', "Mise à jour des dates du semestre.")
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
                    
                    log_activity('IMPORT', 'Emploi du temps', f"Importation réussie : {len(df)} lignes, {prof_count} nouveaux profs.")
                    flash(f"Succès ! {len(df)} lignes importées dans l'emploi du temps. {prof_count} nouveaux professeurs ajoutés.", "success")
            except Exception as e:
                flash(f"Erreur critique lors de la lecture du fichier : {str(e)}", "danger")
            
            return redirect(url_for('manage_data'))

    # Load UI Data
    try: 
        all_profs = db.execute("SELECT DISTINCT Professeur FROM MasterSchedule ORDER BY Professeur").fetchall()
    except: 
        all_profs = []

    saved_statuses = {row['name']: row['status'] for row in db.execute("SELECT * FROM Professors").fetchall()}
    prof_list = [{'name': p['Professeur'], 'status': saved_statuses.get(p['Professeur'], 'Vacataire')} for p in all_profs]

    s_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    
    # NOUVEAU : Récupération du statut d'export pour le Toggle HTML
    export_row = db.execute("SELECT value FROM Config WHERE key='export_visibility'").fetchone()
    export_status = export_row['value'] if export_row else 'hidden'
    
    return render_template('manage.html', 
                           s=s_row['value'] if s_row else "2025-10-06", 
                           e=e_row['value'] if e_row else "2025-12-27",
                           professors=prof_list,
                           export_status=export_status) # <-- Envoyé au HTML ici


# Toggle Export Visibility (AJOUTER CECI DANS APP.PY)
@app.route('/toggle_export_status', methods=['POST'])
@login_required
def toggle_export_status():
    # On convertit le rôle en minuscules pour éviter l'erreur 403 (Admin vs admin)
    user_role = session.get('role', '').lower()
    
    if user_role != 'admin':
        return jsonify({'status': 'error', 'message': 'Accès refusé'}), 403
    
    db = get_db()
    current = db.execute("SELECT value FROM Config WHERE key='export_visibility'").fetchone()
    
    # Si c'était caché, on rend visible. Sinon on cache.
    new_status = 'visible' if (not current or current['value'] == 'hidden') else 'hidden'
    
    db.execute("INSERT OR REPLACE INTO Config (key, value) VALUES ('export_visibility', ?)", (new_status,))
    db.commit()
    
    # Essayer d'enregistrer dans les logs (ignore si la fonction n'existe pas)
    try:
        action_fr = "activé" if new_status == 'visible' else "désactivé"
        log_activity('SÉCURITÉ', 'Paramètres', f"L'administrateur a {action_fr} l'Export Excel.")
    except Exception:
        pass
    
    return jsonify({'status': 'success', 'new_status': new_status})


# --- GESTION DES CLASSES ET SALLES  ---
@app.route('/admin/classes', methods=['GET', 'POST'])
@login_required
def manage_classes():
    if session.get('role') != 'admin':
        flash("Accès refusé.", "danger")
        return redirect(url_for('dashboard'))

    db = get_db()
    
    db.execute('''CREATE TABLE IF NOT EXISTS Salles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS Affectations_Futures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filiere TEXT, jour TEXT, heure TEXT, salle TEXT
        )
    ''')

    # --- TRAITEMENT DES FORMULAIRES ---
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'add_class':
            new_name = request.form.get('class_name').strip()
            if new_name:
                try:
                    db.execute("INSERT INTO Salles (name) VALUES (?)", (new_name,))
                    db.commit()
                    flash(f"La salle '{new_name}' a été ajoutée.", "success")
                except sqlite3.IntegrityError:
                    flash("Cette salle existe déjà.", "danger")
                    
        # GESTION DU PLANIFICATEUR FUTUR
        elif form_type == 'add_affectation':
            filiere = request.form.get('filiere')
            jour = request.form.get('jour')
            heure = request.form.get('heure')
            salle = request.form.get('salle')
            
            conflit = db.execute("SELECT filiere FROM Affectations_Futures WHERE jour = ? AND heure = ? AND salle = ?", (jour, heure, salle)).fetchone()
            if conflit: flash(f"Conflit : La salle {salle} est déjà affectée à {conflit['filiere']} ce jour-là.", "danger")
            else:
                db.execute("INSERT INTO Affectations_Futures (filiere, jour, heure, salle) VALUES (?, ?, ?, ?)", (filiere, jour, heure, salle))
                db.commit()
                flash("Affectation enregistrée dans le planificateur.", "success")
                
        elif form_type == 'delete_affectation':
            db.execute("DELETE FROM Affectations_Futures WHERE id = ?", (request.form.get('affectation_id'),))
            db.commit()
            
        elif form_type == 'clear_all_affectations':
            db.execute("DELETE FROM Affectations_Futures")
            db.commit()
            flash("Le planificateur a été réinitialisé.", "success")

        # NOUVEAU : AJOUTER MANUELLEMENT AU MASTER SCHEDULE ACTUEL
        elif form_type == 'add_master_schedule':
            prof = request.form.get('professeur')
            module = request.form.get('module')
            filiere = request.form.get('filiere')
            semestre = request.form.get('semestre')
            groupe = request.form.get('groupe')
            jour = request.form.get('jour')
            heure = request.form.get('heure')
            salle = request.form.get('salle')
            
            db.execute("""INSERT INTO MasterSchedule (Professeur, Module, Filiere, Semestre, Groupe, Jour, Lheure, Salle) 
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", 
                       (prof, module, filiere, semestre, groupe, jour, heure, salle))
            db.commit()
            log_activity('AJOUT', 'Emploi du temps', f"Séance manuelle ajoutée pour {prof} en {filiere}")
            flash("La séance a été ajoutée à l'emploi du temps actuel avec succès !", "success")

        # NOUVEAU : SUPPRIMER DU MASTER SCHEDULE ACTUEL
        elif form_type == 'delete_master_schedule':
            row_id = request.form.get('rowid')
            db.execute("DELETE FROM MasterSchedule WHERE rowid = ?", (row_id,))
            db.commit()
            log_activity('SUPPRESSION', 'Emploi du temps', f"Séance supprimée de l'emploi du temps actuel.")
            flash("Séance supprimée définitivement de l'emploi du temps actuel.", "info")

        return redirect(url_for('manage_classes'))

    # --- PRÉPARATION DES DONNÉES ---
    my_classes = [dict(row) for row in db.execute("SELECT id, name FROM Salles ORDER BY name").fetchall()]

    # Ajout du `rowid` pour pouvoir supprimer des lignes spécifiques
    try: current_schedule = [dict(row) for row in db.execute("SELECT rowid, * FROM MasterSchedule WHERE Salle IS NOT NULL AND Salle != ''").fetchall()]
    except: current_schedule = []

    future_schedules = [dict(row) for row in db.execute("SELECT * FROM Affectations_Futures").fetchall()]

    # Récupération dynamique de la Base de Données
    try: filieres = [row['nom'] for row in db.execute("SELECT nom FROM Filieres ORDER BY nom").fetchall()]
    except: filieres = []
    
    try: professeurs = [row['name'] for row in db.execute("SELECT name FROM Professors ORDER BY name").fetchall()]
    except: professeurs = []
    
    try: modules = [row['nom'] for row in db.execute("SELECT nom FROM Modules ORDER BY nom").fetchall()]
    except: modules = []

    try: semestres = [row['nom'] for row in db.execute("SELECT nom FROM Semestres ORDER BY nom").fetchall()]
    except: semestres = []

    try: groupes = [row['nom'] for row in db.execute("SELECT nom FROM Groupes ORDER BY nom").fetchall()]
    except: groupes = []

    creneaux = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]

    return render_template('Classe.html', 
                           classes=my_classes, current_schedule=current_schedule, future_schedules=future_schedules,
                           filieres=filieres, professeurs=professeurs, modules=modules, 
                           semestres=semestres, groupes=groupes, jours=jours, creneaux=creneaux)

    # --- PRÉPARATION DES DONNÉES POUR L'AFFICHAGE ---
    
    # Toutes les salles
    my_classes = [dict(row) for row in db.execute("SELECT id, name FROM Salles ORDER BY name").fetchall()]

    # Emploi du temps ACTUEL (Sert uniquement pour l'onglet 2 : "Salles Vides" d'aujourd'hui)
    try:
        current_schedule = [dict(row) for row in db.execute("SELECT * FROM MasterSchedule WHERE Salle IS NOT NULL AND Salle != ''").fetchall()]
    except:
        current_schedule = []

    # Emploi du temps FUTUR (Sert pour l'onglet 3 : Le planificateur)
    future_schedules = [dict(row) for row in db.execute("SELECT * FROM Affectations_Futures").fetchall()]

    # Récupérer la vraie liste des filières de votre base de données
    try:
        filieres = [row['nom'] for row in db.execute("SELECT nom FROM Filieres ORDER BY nom").fetchall()]
    except:
        filieres = ["Amazigh", "SMI", "Mathématiques"] # Fallback au cas où

    creneaux = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]

    return render_template('Classe.html', 
                           classes=my_classes, 
                           current_schedule=current_schedule,
                           future_schedules=future_schedules,
                           filieres=filieres,
                           jours=jours,
                           creneaux=creneaux)



# --- GESTION DES STATUTS DES PROFESSEURS (PERMANENT / VACATAIRE) ---

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
                # --- LOG  ---
                log_activity('AJOUT', 'Professeurs', f"Nouveau professeur : {new_prof} ({new_status})")
                # ----------------
                flash(f"Professeur {new_prof} ajouté avec succès.")
            except sqlite3.IntegrityError:
                flash(f"Le professeur {new_prof} existe déjà dans la base.")
        return redirect(url_for('prof_status'))

    try:
        professors = db.execute("SELECT name, status FROM Professors ORDER BY name ASC").fetchall()
    except sqlite3.OperationalError:
        professors = []
    return render_template('prof_status.html', professors=professors)

# --- ROUTE POUR TOGGLER LE STATUT D'UN PROFESSEUR (PERMANENT <-> VACATAIRE) ---
@app.route('/toggle_status/<name>')
@login_required
def toggle_status(name):
    db = get_db()
    prof = db.execute("SELECT status FROM Professors WHERE name = ?", (name,)).fetchone()
    if prof:
        new_status = "Vacataire" if prof['status'] == "Permanent" else "Permanent"
        db.execute("UPDATE Professors SET status = ? WHERE name = ?", (new_status, name))
        db.commit()
        # --- LOG  ---
        log_activity('MODIFICATION', 'Professeurs', f"Statut de {name} changé en {new_status}")
        # ----------------
        flash(f"Le statut de {name} a été changé en {new_status}.")
    return redirect(url_for('prof_status'))



# --- NOUVELLE API POUR LES SALLES LIBRES  & Modules ---
# --- API MISE À JOUR : SALLES HABITUELLES + SALLES LIBRES ---

@app.route('/api/available_rooms')
@login_required
def available_rooms():
    try:
        db = get_db()
        date_str = request.args.get('date')
        time_slot = request.args.get('time_slot')
        prof = request.args.get('prof', '').strip()
        module = request.args.get('module', '').strip()

        if not time_slot:
            return jsonify({'usual': [], 'available': []})

        # 1. Obtenir le jour de la semaine (Ex: "Lundi")
        try:
            if date_str:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                day_of_week = days[date_obj.weekday()]
            else:
                day_of_week = ""
        except Exception:
            day_of_week = ""

        # 2. Salles habituelles (Tolérance maximale aux espaces avec LIKE)
        usual_rooms = []
        if prof and module:
            # Les % autour permettent de trouver "Essahabi " même si on cherche "Essahabi"
            u_res = db.execute("""
                SELECT DISTINCT Salle 
                FROM MasterSchedule 
                WHERE Professeur LIKE ? AND Module LIKE ? 
                AND Salle IS NOT NULL AND Salle != ''
            """, (f"%{prof}%", f"%{module}%")).fetchall()
            usual_rooms = [r['Salle'].strip() for r in u_res if r['Salle']]

        # 3. Toutes les salles existantes
        all_rooms_query = db.execute("SELECT DISTINCT Salle FROM MasterSchedule WHERE Salle IS NOT NULL AND Salle != ''").fetchall()
        all_rooms = {r['Salle'].strip() for r in all_rooms_query if r['Salle']}

        # 4. Occupations et Salles Virtuelles (P-1 / P-2)
        # On utilise LIKE pour être tolérant aux espaces dans les heures/jours
        occ_ms = db.execute("""
            SELECT Salle, Professeur, Module 
            FROM MasterSchedule 
            WHERE Jour LIKE ? AND Lheure LIKE ?
        """, (f"%{day_of_week}%", f"%{time_slot}%")).fetchall()
        
        occupied = set()
        virtual_rooms = set()
        
        poly_1 = ['PLOYVALENTE 1', 'POLYVALENTE 1']
        poly_2 = ['PLOYVALENTE 2', 'POLYVALENTE 2']

        prof_upper = prof.upper()
        module_upper = module.upper()

        def check_polyvalente(r):
            if not r['Salle']: return
            salle_clean = str(r['Salle']).strip()
            p_clean = str(r['Professeur']).strip().upper()
            m_clean = str(r['Module']).strip().upper()

            # La salle physique est marquée occupée
            occupied.add(salle_clean)

            # Si c'est notre prof et notre module dans la Polyvalente, on débloque P-1 ou P-2
            if salle_clean.upper() in poly_1 and prof_upper in p_clean and module_upper in m_clean:
                virtual_rooms.add('P-1')
            if salle_clean.upper() in poly_1 and prof_upper in p_clean and module_upper in m_clean:
                virtual_rooms.add('P-1-1')
            if salle_clean.upper() in poly_2 and prof_upper in p_clean and module_upper in m_clean:
                virtual_rooms.add('P-2')
            if salle_clean.upper() in poly_2 and prof_upper in p_clean and module_upper in m_clean:
                virtual_rooms.add('P-2-1')

        # Vérifier l'emploi du temps normal
        for r in occ_ms:
            check_polyvalente(r)

        # Vérifier les rattrapages programmés ce jour-là
        if date_str:
            occ_ratt = db.execute("""
                SELECT Salle, Professeur, Module 
                FROM RattSessions 
                WHERE date_ratt = ? AND Lheure LIKE ?
            """, (date_str, f"%{time_slot}%")).fetchall()
            for r in occ_ratt:
                check_polyvalente(r)

        # 5. Calcul Final
        available = sorted(list((all_rooms | virtual_rooms) - occupied))
        usual_rooms = list(set(usual_rooms)) # Enlever les doublons

        return jsonify({'usual': usual_rooms, 'available': available})
    
    except Exception as e:
        print(f"--- ERREUR CRITIQUE API SALLES : {str(e)} ---")
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
    
# --- 1. API MODULES Par Filiére ---
@app.route('/api/modules_by_filiere', methods=['GET'])
@login_required
def api_modules_by_filiere():
    """
    Renvoie la liste des modules filtrés par filière et par semestre.
    Utilisé par l'autocomplétion JavaScript lors de la création d'un emploi du temps.
    """
    filiere = request.args.get('filiere', '').strip()
    semestre = request.args.get('semestre', '').strip()
    
    db = get_db()
    
    # Construction de la requête dynamique
    query = "SELECT nom FROM Modules WHERE 1=1"
    params = []
    
    if filiere:
        query += " AND filiere = ?"
        params.append(filiere)
        
    if semestre:
        query += " AND semestre = ?"
        params.append(semestre)
        
    query += " ORDER BY nom"
    
    try:
        modules_rows = db.execute(query, params).fetchall()
        # On extrait juste les noms sous forme de liste de texte
        modules_list = [row['nom'] for row in modules_rows]
    except sqlite3.OperationalError:
        # Au cas où la table n'a pas encore les colonnes filiere/semestre
        # (Sécurité pour éviter que l'application ne plante)
        try:
            fallback = db.execute("SELECT nom FROM Modules ORDER BY nom").fetchall()
            modules_list = [row['nom'] for row in fallback]
        except:
            modules_list = []
            
    return jsonify(modules_list)

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

    # DOUBLE-BOOKING AVEC EXCEPTION P-1 / P-2 ---
    
    # Vérification 1 : Le professeur a-t-il déjà un rattrapage à cette heure ?
    prof_ratts = db.execute("SELECT * FROM RattSessions WHERE Professeur = ? AND date_ratt = ? AND Lheure = ?", (prof, date_ratt, time_slot)).fetchall()
    
    for r in prof_ratts:
        # EXCEPTION : Si la salle choisie est P-1 ou P-2, ET que le module est identique, on autorise
        if salle in ['P-1', 'P-2'] and r['Module'] == module_name:
            continue # On ignore ce conflit et on passe à la suite
        else:
            flash(f"Erreur : Le professeur {prof} a déjà un rattrapage programmé le {date_ratt} de {time_slot}.", "danger")
            return redirect(url_for('ratt_session'))

    # Vérification 2 : La salle est-elle déjà prise par un AUTRE rattrapage ?
    # (Cela protègera aussi P-1 et P-2 d'être utilisées plus d'une fois !)
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
    # --- LOG ---
    log_activity('AJOUT', 'Rattrapage', f"Rattrapage programmé pour {prof} ({module_name}) le {date_ratt}")
    # ----------------
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


# Sauvgarder et Recupérer la base de données
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

# --- NOUVELLE API POUR TRAITER LES ABSENCES EN FONCTION DES SALLES LIBRES ---
@app.route('/process_absence', methods=['POST'])
@login_required
def process_absence():
    db = get_db()
    date_str = request.form.get('date')
    time_slot = request.form.get('time_slot')
    empty_rooms = request.form.getlist('empty_rooms')

    if not date_str or not time_slot or not empty_rooms:
        flash("Veuillez remplir tous les champs et sélectionner au moins une salle.", "warning")
        return redirect(request.referrer or url_for('index'))

    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    day_of_week = days[date_obj.weekday()]

    count_new = 0
    count_exist = 0
    rooms_with_no_class = []
    
    # NOUVEAU : On crée une liste pour stocker les détails de qui a été noté absent
    details_ajoutes = []

    for room in empty_rooms:
        schedule_entries = db.execute('''
            SELECT Professeur, Semestre, Filiere, Groupe, Module 
            FROM MasterSchedule 
            WHERE TRIM(Jour) COLLATE NOCASE = ? 
              AND TRIM(Lheure) = ? 
              AND TRIM(Salle) COLLATE NOCASE = ?
        ''', (day_of_week.strip(), time_slot.strip(), room.strip())).fetchall()

        ratt_entries = []
        try:
            ratt_entries = db.execute('''
                SELECT Professeur, Semestre, Filiere, groupe AS Groupe, Module 
                FROM RattSessions 
                WHERE date_ratt = ? 
                  AND TRIM(Lheure) = ? 
                  AND TRIM(Salle) COLLATE NOCASE = ?
            ''', (date_str, time_slot.strip(), room.strip())).fetchall()
        except:
            pass 

        all_entries = schedule_entries + ratt_entries

        if not all_entries:
            rooms_with_no_class.append(room)
            continue

        for entry in all_entries:
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
                count_new += 1
                
                # NOUVEAU : On garde en mémoire le nom du prof et le module pour le log
                details_ajoutes.append(f"{entry['Professeur']} ({entry['Module']})")
            else:
                count_exist += 1

    db.commit()

    # --- LOG ULTRA DÉTAILLÉ ICI ---
    if count_new > 0:
        profs_concatenes = ", ".join(details_ajoutes)
        log_activity('AJOUT', 'Absence', f"{count_new} absence(s) le {date_str} à {time_slot}. Concerne : {profs_concatenes}")
    # ------------------------------

    if count_new > 0:
        flash(f"✅ {count_new} absence(s) enregistrée(s) avec succès.", "success")
    if count_exist > 0:
        flash(f"ℹ️ {count_exist} absence(s) étaient déjà enregistrées dans le système et ont été ignorées.", "info")
    if rooms_with_no_class:
        salles_vides_str = ", ".join(rooms_with_no_class)
        flash(f"⚠️ Attention : Aucun cours n'était prévu dans la base pour ces salles : {salles_vides_str}.", "warning")

    return redirect(request.referrer or url_for('dashboard'))


# --- 1. SUPPRESSION D'UNE SEULE ABSENCE ---
@app.route('/delete_absence/<int:absence_id>', methods=['POST'])
@login_required
def delete_absence(absence_id):
    db = get_db()
    # On récupère les infos AVANT de supprimer
    absent = db.execute("SELECT Professeur, Module, date_absent, Lheure FROM AbsenceRecords WHERE id=?", (absence_id,)).fetchone()
    
    db.execute("DELETE FROM AbsenceRecords WHERE id=?", (absence_id,))
    db.commit()
    
    # On écrit le Log
    if absent:
        desc = f"Annulation de l'absence de {absent['Professeur']} ({absent['Module']}) le {absent['date_absent']} à {absent['Lheure']}."
        log_activity('SUPPRESSION', 'Absence', desc)
    else:
        log_activity('SUPPRESSION', 'Absence', f"Suppression de l'absence ID {absence_id}")
        
    flash("Absence supprimée avec succès.", "info")
    return redirect(request.referrer or url_for('dashboard'))


# --- 2. SUPPRESSION MULTIPLE (Celle qui manquait !) ---
@app.route('/delete_multiple_absences', methods=['POST'])
@login_required
def delete_multiple_absences():
    db = get_db()
    absence_ids = request.form.getlist('absence_ids')
    
    if not absence_ids:
        flash("Aucune absence sélectionnée pour la suppression.", "warning")
        return redirect(request.referrer)
        
    try:
        # Création des '?' pour la requête SQL
        placeholders = ','.join(['?'] * len(absence_ids))
        
        # 1. On lit les profs concernés pour le log
        records = db.execute(f"SELECT Professeur FROM AbsenceRecords WHERE id IN ({placeholders})", absence_ids).fetchall()
        profs_impliques = list(set([r['Professeur'] for r in records])) # Enlève les doublons
        profs_str = ", ".join(profs_impliques)

        # 2. On supprime tout d'un coup
        db.execute(f"DELETE FROM AbsenceRecords WHERE id IN ({placeholders})", absence_ids)
        db.commit()
        
        # 3. On enregistre le Log global
        log_activity('SUPPRESSION', 'Absence', f"Suppression de {len(absence_ids)} absence(s) concernant : {profs_str}")
        
        flash(f"{len(absence_ids)} absence(s) supprimée(s) avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de la suppression multiple : {str(e)}", "danger")
        
    return redirect(request.referrer or url_for('dashboard'))

# --- API POUR TRAITER LES RATT EN FONCTION DES SALLES LIBRES ---
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
    init_core_tables()
    
    # --- 1. Options pour l'EXPLORATEUR (Ce qui est DÉJÀ dans l'emploi du temps) ---
    try:
        filieres = [f['Filiere'] for f in db.execute("SELECT DISTINCT Filiere FROM MasterSchedule WHERE Filiere != '' ORDER BY Filiere").fetchall()]
        semestres = [s['Semestre'] for s in db.execute("SELECT DISTINCT Semestre FROM MasterSchedule WHERE Semestre != '' ORDER BY Semestre").fetchall()]
        groupes = [g['groupe'] for g in db.execute("SELECT DISTINCT groupe FROM MasterSchedule WHERE groupe != '' ORDER BY groupe").fetchall()]
        professeurs = [p['Professeur'] for p in db.execute("SELECT DISTINCT Professeur FROM MasterSchedule WHERE Professeur != '' ORDER BY Professeur").fetchall()]
        modules = [m['Module'] for m in db.execute("SELECT DISTINCT Module FROM MasterSchedule WHERE Module != '' ORDER BY Module").fetchall()]
    except:
        filieres, semestres, groupes, professeurs, modules = [], [], [], [], []

    # --- 1 BIS. Options pour le CRÉATEUR et les MODALS (Toute la vraie Base de Données) ---
    try: all_filieres = [r['nom'] for r in db.execute("SELECT nom FROM Filieres ORDER BY nom").fetchall()]
    except: all_filieres = []
    try: all_semestres = [r['nom'] for r in db.execute("SELECT nom FROM Semestres ORDER BY nom").fetchall()]
    except: all_semestres = []
    try: all_profs = [r['name'] for r in db.execute("SELECT name FROM Professors ORDER BY name").fetchall()]
    except: all_profs = []
    try: all_groupes = [r['nom'] for r in db.execute("SELECT nom FROM Groupes ORDER BY nom").fetchall()]
    except: all_groupes = []
    try: all_modules = [r['nom'] for r in db.execute("SELECT nom FROM Modules ORDER BY nom").fetchall()]
    except: all_modules = []
    
    # TRÈS IMPORTANT : Les modules liés pour le filtre intelligent JavaScript
    try: modules_lies = [dict(r) for r in db.execute("SELECT nom, filiere, semestre FROM Modules").fetchall()]
    except: modules_lies = []

    # --- 2. Paramètres de recherche ---
    search_type = request.args.get('search_type', 'classe') 
    selected_filiere = request.args.get('filiere', '')
    selected_semestre = request.args.get('semestre', '')
    selected_groupe = request.args.get('groupe', 'ALL')
    selected_prof = request.args.get('professeur', '')
    selected_module = request.args.get('module', '')
    
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    time_slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    
    grid = {h: {j: [] for j in jours} for h in time_slots}
    has_data = False
    schedule_title = ""

    # --- 3. Remplissage de la grille ---
    if search_type in ['classe', 'create'] and selected_filiere and selected_semestre:
        # CORRECTION ICI : On a ajouté "Filiere, Semestre" dans le SELECT
        query = "SELECT rowid AS id, Jour, Lheure, Professeur, Module, Salle, groupe, Filiere, Semestre FROM MasterSchedule WHERE Filiere = ? AND Semestre = ?"
        params = [selected_filiere, selected_semestre]
        if selected_groupe != 'ALL' and selected_groupe != '':
            query += " AND groupe = ?"
            params.append(selected_groupe)
        schedule_data = db.execute(query, params).fetchall()
        grp_text = f" - {selected_groupe}" if selected_groupe != 'ALL' and selected_groupe else " - Vue Globale"
        
        if search_type == 'create':
            schedule_title = f"🛠️ Créateur de Planning : {selected_filiere} (S{selected_semestre}){grp_text}"
        else:
            schedule_title = f"{selected_filiere} (S{selected_semestre}){grp_text}"
            
    elif search_type == 'prof' and selected_prof:
        schedule_data = db.execute("SELECT rowid AS id, Jour, Lheure, Filiere, Semestre, Module, Salle, groupe FROM MasterSchedule WHERE Professeur = ?", [selected_prof]).fetchall()
        schedule_title = f"Emploi du temps : {selected_prof}"
        
    elif search_type == 'module' and selected_module:
        schedule_data = db.execute("SELECT rowid AS id, Jour, Lheure, Professeur, Filiere, Semestre, Salle, groupe FROM MasterSchedule WHERE Module = ?", [selected_module]).fetchall()
        schedule_title = f"Module : {selected_module}"
    else:
        schedule_data = []

    for row in schedule_data:
        j = row['Jour'].capitalize().strip()
        h = row['Lheure'].strip()
        if h in grid and j in grid[h]:
            grid[h][j].append(row)
            has_data = True

    # Force l'affichage de la grille vide pour pouvoir créer
    if search_type == 'create':
        has_data = True

    return render_template('schedule.html', 
                           filieres=filieres, semestres=semestres, groupes=groupes,
                           professeurs=professeurs, modules=modules,
                           all_filieres=all_filieres, all_semestres=all_semestres, all_profs=all_profs, 
                           all_groupes=all_groupes, all_modules=all_modules, modules_lies=modules_lies,
                           search_type=search_type,
                           selected_filiere=selected_filiere, selected_semestre=selected_semestre, selected_groupe=selected_groupe,
                           selected_prof=selected_prof, selected_module=selected_module,
                           jours=jours, time_slots=time_slots, grid=grid, has_data=has_data, schedule_title=schedule_title)

# --- GESTION DES Emplois de Temps ---
# --- GESTION DES Emplois de Temps ---
@app.route('/add_schedule', methods=['POST'])
@login_required
def add_schedule():
    db = get_db()
    # Récupération des données du modal
    jour = request.form.get('jour')
    heure = request.form.get('heure')
    # CORRECTION ICI : On retire .upper() pour garder "Pr." intact !
    prof = request.form.get('prof', '').strip() 
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

        # --- NOUVEAU : ENREGISTREMENT DU LOG ---
        log_activity('AJOUT', 'Emploi du Temps', f"Nouveau cours pour {prof} en {salle} le {jour} à {heure}.")
        # ---------------------------------------
        flash(f"Nouvelle séance ajoutée pour {prof} le {jour} à {heure}.", "success")
    else:
        flash("Erreur : Veuillez remplir les champs obligatoires (Filière, Semestre, Professeur).", "danger")
    return redirect(request.referrer or url_for('view_schedule'))

@app.route('/edit_schedule', methods=['POST'])
@login_required
def edit_schedule():
    db = get_db()
    slot_id = request.form.get('slot_id')
    new_prof = request.form.get('new_prof', '').strip()
    new_module = request.form.get('new_module', '').strip()
    new_salle = request.form.get('new_salle', '').strip()
    
    if slot_id:
        # 1. On récupère l'ancienne séance pour voir ce qui va changer
        old_record = db.execute("SELECT Professeur, Module, Salle FROM MasterSchedule WHERE rowid = ?", (slot_id,)).fetchone()
        
        # 2. On met à jour TOUTES les valeurs (Prof, Module, Salle)
        db.execute("""
            UPDATE MasterSchedule 
            SET Professeur = ?, Module = ?, Salle = ?
            WHERE rowid = ?
        """, (new_prof, new_module, new_salle, slot_id))
        db.commit()
        
        # 3. On crée un message de confirmation dynamique et intelligent !
        chagements = []
        if old_record:
            if old_record['Professeur'] != new_prof:
                chagements.append(f"Professeur ➔ {new_prof}")
            if old_record['Salle'] != new_salle:
                chagements.append(f"Salle ➔ {new_salle}")
            if old_record['Module'] != new_module:
                chagements.append(f"Module ➔ {new_module}")
        
        # S'il y a eu des modifications réelles
        if chagements:
            details = ", ".join(chagements)

            # --- NOUVEAU : ENREGISTREMENT DU LOG ---
            log_activity('MODIFICATION', 'Emploi du Temps', f"Mise à jour du cours ID {slot_id}. Changements : {details}")
            # ---------------------------------------
            flash(f"✅ Séance mise à jour avec succès. Modifications : {details}", "success")
        else:
            flash("ℹ️ Séance enregistrée (aucun changement détecté).", "info")
            
    else:
        flash("Erreur lors de la modification : ID de la séance manquant.", "danger")
        
    return redirect(request.referrer or url_for('view_schedule'))

@app.route('/delete_schedule/<int:slot_id>', methods=['POST'])
@login_required
def delete_schedule(slot_id):
    db = get_db()
    cours = db.execute("SELECT Professeur, Module, Jour FROM MasterSchedule WHERE rowid = ?", (slot_id,)).fetchone()
    desc = f"Suppression du cours de {cours['Professeur']} ({cours['Module']}) le {cours['Jour']}." if cours else f"Suppression de l'ID {slot_id}."
    try:
        db.execute("DELETE FROM MasterSchedule WHERE rowid = ?", (slot_id,))
        db.commit()
        # --- NOUVEAU : ENREGISTREMENT DU LOG ---
        log_activity('SUPPRESSION', 'Emploi du Temps', desc)
        # ---------------------------------------
        flash("Séance supprimée avec succès.", "success")
    except Exception as e:
        flash(f"Erreur lors de la suppression : {str(e)}", "danger")
    return redirect(request.referrer or url_for('view_schedule'))


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

                # --- LOG ---
                log_activity('AJOUT', 'Calendrier', f"Nouvelle période : {h_desc} (du {d_start} au {d_end})")
                # ----------------
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
    # --- LOG  ---
    log_activity('SUPPRESSION', 'Calendrier', f"Suppression d'une période exceptionnelle (ID: {h_id})")
    # ----------------
    flash("Période exceptionnelle supprimée.", "success")
    return redirect(url_for('manage_holidays'))


# Delete Ratt Route

@app.route('/delete_ratt/<int:ratt_id>', methods=['POST'])
@login_required
def delete_ratt(ratt_id):
    db = get_db()
    cours = db.execute("SELECT Professeur, Module, date_ratt FROM RattSessions WHERE id = ?", (ratt_id,)).fetchone()
    try:
        db.execute("DELETE FROM RattSessions WHERE id = ?", (ratt_id,))
        db.commit()
        # --- NOUVEAU : ENREGISTREMENT DU LOG ---
        log_activity('SUPPRESSION', 'Rattrapage', f"Suppression du rattrapage de {cours['Professeur']} ({cours['Module']}) le {cours['date_ratt']}.")
        # ---------------------------------------
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
    # 1. SÉCURITÉ : Bloquer l'accès si ce n'est pas l'Administrateur
    user_role = session.get('role', '').lower()
    if user_role != 'admin':
        flash("Accès refusé. Action réservée à l'administrateur.", "danger")
        return redirect(url_for('dashboard'))

    db = get_db()
    
    # 2. EFFACEMENT DES DONNÉES TRANSACTIONNELLES (Le quotidien)
    db.execute("DELETE FROM AbsenceRecords")
    db.execute("DELETE FROM RattSessions")
    db.execute("DELETE FROM MasterSchedule")
    db.execute("DELETE FROM Holidays")
    
    # 3. OPTIMISATION ERP : Réinitialiser les compteurs (ID) à zéro
    # Comme ça, la première absence du nouveau semestre aura l'ID n°1
    try:
        db.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name IN ('AbsenceRecords', 'RattSessions', 'MasterSchedule', 'Holidays')")
    except Exception:
        pass # Ignore si la table système sqlite_sequence n'est pas encore créée
        
    db.commit()
    
    # 4. TRACABILITÉ : Enregistrer l'action dans le journal
    username = session.get('username', 'Admin')
    log_activity('SYSTÈME', 'Fin de Semestre', f"Réinitialisation des emplois du temps et absences par {username}. Données de base conservées.")
    
    # 5. RETOUR UTILISATEUR
    flash("Le semestre a été réinitialisé ! L'emploi du temps, les absences et les rattrapages ont été effacés. Vos professeurs, modules, filières et groupes ont été conservés intacts.", "success")
    
    # Remarque : Mettez ici le bon nom de votre route pour la page des paramètres
    # Si votre route s'appelle manage_data(), remettez 'manage_data' à la place de 'manage_data'
    return redirect(url_for('manage_data'))


# FIX 9: The networking code at the end is completed safely
if __name__ == '__main__':
    with app.app_context():
     init_db()
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