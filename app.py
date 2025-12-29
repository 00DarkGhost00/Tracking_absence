import os, sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, g
from flask import send_file
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'esef_manager_2025'
DATABASE = 'absence_tracker.db'


# --- BACKUP & RESTORE ROUTES ---

@app.route('/export_db')
def export_db():
    # This sends the actual database file to the user's browser
    return send_file(DATABASE, as_attachment=True, download_name=f"backup_esef_{datetime.now().strftime('%Y-%m-%d')}.db")

@app.route('/restore_db', methods=['POST'])
def restore_db():
    if 'backup_file' in request.files:
        file = request.files['backup_file']
        if file.filename.endswith('.db'):
            # Close connection before replacing the file
            db = getattr(g, '_database', None)
            if db is not None: db.close()
            
            # Save the uploaded file as the new active database
            file.save(DATABASE)
            return redirect(url_for('manage_data'))
    return "Fichier invalide. Veuillez télécharger un fichier .db", 400


# --- 1. DATABASE SETUP ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        # Create tables from scratch
        db.execute("CREATE TABLE IF NOT EXISTS Config (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("""CREATE TABLE IF NOT EXISTS AbsenceRecords (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date_absent TEXT, Professeur TEXT, 
            Semestre TEXT, Filiere TEXT, Groupe TEXT, Jour TEXT, Lheure TEXT, Salle TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS RattSessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date_ratt TEXT, Professeur TEXT, Lheure TEXT)""")
    return db

@app.teardown_appcontext
def close_connection(e):
    db = getattr(g, '_database', None)
    if db is not None: db.close()



# --- 2. LOGIC: THEORETICAL HOUR CALCULATION (CALENDAR BASED) ---
def get_stats_for_prof(prof_name):
    db = get_db()
    
    # Get Semester Dates from Config (Defaults to your specific range)
    start_row = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    end_row = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    
    s_val = start_row['value'] if start_row else "2025-10-06"
    e_val = end_row['value'] if end_row else "2025-12-27"
    
    try:
        start_date = datetime.strptime(s_val, '%Y-%m-%d')
        end_date = datetime.strptime(e_val, '%Y-%m-%d')
    except:
        start_date, end_date = datetime(2025,10,6), datetime(2025,12,27)

    # A. THEORETICAL HOURS: Iterate through the weeks of the semester
    schedule = db.execute("SELECT Jour FROM MasterSchedule WHERE Professeur = ?", (prof_name,)).fetchall()
    scheduled_days = [r['Jour'] for r in schedule]
    
    theo_hrs = 0
    if scheduled_days:
        day_map = {0:'Lundi', 1:'Mardi', 2:'Mercredi', 3:'Jeudi', 4:'Vendredi', 5:'Samedi', 6:'Dimanche'}
        current = start_date
        while current <= end_date:
            french_day = day_map[current.weekday()]
            if french_day in scheduled_days:
                # Multiply by 3h for every instance of that day in their weekly schedule
                theo_hrs += (scheduled_days.count(french_day) * 3)
            current += timedelta(days=1)
    
    # B. ABSENCES & RATTRAPAGES
    abs_row = db.execute("SELECT COUNT(*) FROM AbsenceRecords WHERE Professeur = ?", (prof_name,)).fetchone()
    abs_h = abs_row[0] * 3 if abs_row else 0
    
    ratt_row = db.execute("SELECT COUNT(*) FROM RattSessions WHERE Professeur = ?", (prof_name,)).fetchone()
    ratt_h = ratt_row[0] * 3 if ratt_row else 0
    
    real = (theo_hrs - abs_h) + ratt_h
    return theo_hrs, abs_h, ratt_h, real

# --- 3. ROUTES ---

@app.route('/')
def index():
    db = get_db()
    try:
        rooms = [r[0] for r in db.execute("SELECT DISTINCT Salle FROM MasterSchedule ORDER BY Salle")]
    except: rooms = []
    slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    return render_template('index.html', rooms=rooms, time_slots=slots, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/process_absence', methods=['POST'])
def process_absence():
    db = get_db()
    d, s, rms = request.form['date'], request.form['time_slot'], request.form.getlist('empty_rooms')
    day_en = pd.to_datetime(d).day_name()
    day_map = {'Monday':'Lundi','Tuesday':'Mardi','Wednesday':'Mercredi','Thursday':'Jeudi','Friday':'Vendredi','Saturday':'Samedi','Sunday':'Dimanche'}
    french_day = day_map.get(day_en)

    if rms:
        placeholders = ','.join('?' * len(rms))
        query = f"SELECT * FROM MasterSchedule WHERE Jour=? AND Lheure=? AND Salle IN ({placeholders})"
        targets = db.execute(query, [french_day, s] + rms).fetchall()
        for r in targets:
            # Handle possible encoding issues in column names
            filiere = r['Filiere'] if 'Filiere' in r.keys() else r.get('FiliÃ©re', r.get('Filiére', 'N/A'))
            db.execute("""INSERT INTO AbsenceRecords (date_absent, Professeur, Semestre, Filiere, Groupe, Jour, Lheure, Salle) 
                          VALUES (?,?,?,?,?,?,?,?)""", 
                       (d, r['Professeur'], r['Semestre'], filiere, r['Groupe'], r['Jour'], r['Lheure'], r['Salle']))
        db.commit()
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    db = get_db()
    recent = db.execute("SELECT * FROM AbsenceRecords ORDER BY id DESC LIMIT 15").fetchall()
    top_p = db.execute("SELECT Professeur, COUNT(*) as c FROM AbsenceRecords GROUP BY Professeur ORDER BY c DESC LIMIT 1").fetchone()
    top_f = db.execute("SELECT Filiere, COUNT(*) as c FROM AbsenceRecords GROUP BY Filiere ORDER BY c DESC LIMIT 1").fetchone()
    top_d = db.execute("SELECT Jour, COUNT(*) as c FROM AbsenceRecords GROUP BY Jour ORDER BY c DESC LIMIT 1").fetchone()
    return render_template('dashboard.html', recent_absences=recent, top_prof=top_p, top_filiere=top_f, top_day=top_d)

@app.route('/professors')
def professors_list():
    db = get_db()
    try: profs = db.execute("SELECT DISTINCT Professeur FROM MasterSchedule ORDER BY Professeur").fetchall()
    except: profs = []
    data = []
    for p in profs:
        theo, abs_h, ratt_h, real = get_stats_for_prof(p['Professeur'])
        data.append({'name': p['Professeur'], 'theo': theo, 'abs': abs_h, 'ratt': ratt_h, 'real': real})
    return render_template('professors.html', data=data)

@app.route('/professor/<path:prof_name>')
def professor_details(prof_name):
    db = get_db()
    theo, abs_h, ratt_h, real = get_stats_for_prof(prof_name)
    absences = db.execute("SELECT * FROM AbsenceRecords WHERE Professeur=? ORDER BY id DESC", (prof_name,)).fetchall()
    rattrapages = db.execute("SELECT * FROM RattSessions WHERE Professeur=? ORDER BY date_ratt DESC", (prof_name,)).fetchall()
    s = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    return render_template('professor_details.html', prof_name=prof_name, theo=theo, abs_h=abs_h, ratt_h=ratt_h, real=real,
                           absences=absences, rattrapages=rattrapages, 
                           sem_start=s['value'] if s else "2025-10-06", sem_end=e['value'] if e else "2025-12-27")

# --- THIS IS THE MISSING ROUTE CAUSING THE BUILDERROR ---
@app.route('/ratt_session')
def ratt_session():
    db = get_db()
    try: profs = db.execute("SELECT DISTINCT Professeur FROM MasterSchedule ORDER BY Professeur").fetchall()
    except: profs = []
    slots = ["8h30 - 11h30", "11h45 - 14h45", "15h00 - 18h00"]
    return render_template('ratt_session.html', professors=profs, time_slots=slots, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/process_ratt', methods=['POST'])
def process_ratt():
    db = get_db()
    db.execute("INSERT INTO RattSessions (date_ratt, Professeur, Lheure) VALUES (?,?,?)", 
               (request.form['date'], request.form['prof'], request.form['slot']))
    db.commit()
    return redirect(url_for('professors_list'))

@app.route('/manage', methods=['GET', 'POST'])
def manage_data():
    db = get_db()
    if request.method == 'POST':
        if 'sem_start' in request.form:
            db.execute("INSERT OR REPLACE INTO Config VALUES ('sem_start', ?)", (request.form['sem_start'],))
            db.execute("INSERT OR REPLACE INTO Config VALUES ('sem_end', ?)", (request.form['sem_end'],))
        if 'file' in request.files and request.files['file'].filename != '':
            f = request.files['file']
            f.save("temp.csv")
            df = pd.read_csv("temp.csv", sep=';', encoding='latin-1')
            df.columns = [c.replace('FiliÃ©re', 'Filiere').replace('Filiére', 'Filiere').strip() for c in df.columns]
            df = df.drop_duplicates()
            conn = sqlite3.connect(DATABASE)
            df.to_sql('MasterSchedule', conn, if_exists='replace', index=False)
            conn.close()
        db.commit()
        return redirect(url_for('manage_data'))
    s = db.execute("SELECT value FROM Config WHERE key='sem_start'").fetchone()
    e = db.execute("SELECT value FROM Config WHERE key='sem_end'").fetchone()
    return render_template('manage.html', s=s['value'] if s else "2025-10-06", e=e['value'] if e else "2025-12-27")

@app.route('/delete/<int:absence_id>', methods=['POST'])
def delete_absence(absence_id):
    db = get_db()
    db.execute("DELETE FROM AbsenceRecords WHERE id=?", (absence_id,))
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/reset_semester', methods=['POST'])
def reset_semester():
    db = get_db()
    # We clear the schedule, the absences, and the rattrapages
    db.execute("DELETE FROM MasterSchedule")
    db.execute("DELETE FROM AbsenceRecords")
    db.execute("DELETE FROM RattSessions")
    db.commit()
    return redirect(url_for('manage_data'))

if __name__ == '__main__':
    app.run(debug=True)