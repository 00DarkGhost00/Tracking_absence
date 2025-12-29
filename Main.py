from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
from datetime import datetime
import pandas as pd # Used for robust date/day conversion

# --- Configuration ---
DATABASE = 'absence_tracker.db'
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key' 

# --- Database Connection Management ---

def get_db():
    """Connects to the database and returns the connection object."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        # sqlite3.Row allows us to access columns by name (e.g., row['Professeur'])
        db.row_factory = sqlite3.Row 
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection when the request is finished."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def get_unique_rooms_and_slots():
    """Retrieves all rooms from the schedule for the data entry form."""
    db = get_db()
    cursor = db.cursor()
    
    # Get all unique salle names from the MasterSchedule
    rooms = [row[0] for row in cursor.execute("SELECT DISTINCT Salle FROM MasterSchedule ORDER BY Salle")]
    
    # The time slots are fixed based on your original paper process
    time_slots = [
        "8h30 - 11h30",
        "11h45 - 14h45",
        "15h00 - 18h00"
    ]
    return rooms, time_slots

# --- Web Routes (URLs) ---

@app.route('/', methods=['GET'])
def index():
    """Renders the main data entry form."""
    rooms, time_slots = get_unique_rooms_and_slots()
    
    # Pre-fills the date field with today's date
    today = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('index.html', rooms=rooms, time_slots=time_slots, today=today)

@app.route('/process_absence', methods=['POST'])
def process_absence():
    """CORE LOGIC: Finds and records absences based on empty rooms."""
    db = get_db()
    cursor = db.cursor()
    
    # 1. Get data from the form
    input_date = request.form['date']
    time_slot = request.form['time_slot']
    # request.form.getlist handles multiple checkbox selections
    empty_rooms = request.form.getlist('empty_rooms') 
    
    if not input_date or not time_slot or not empty_rooms:
        return "Error: Missing date, time slot, or empty rooms.", 400

    # 2. Convert the input date to the French day name (Lundi, Mardi, etc.)
    try:
        date_obj = pd.to_datetime(input_date)
        day_of_week_english = date_obj.day_name()
    except ValueError:
        return "Error: Invalid date format.", 400

    day_mapping = {
        'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi', 
        'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 
        'Sunday': 'Dimanche'
    }
    target_jour = day_mapping.get(day_of_week_english, 'UNKNOWN')

    # 3. Find Scheduled Classes in the Empty Rooms (These are the ABSENCES)
    
    # Use placeholders for safe SQL querying
    placeholders = ','.join('?' * len(empty_rooms)) 
    
    query = f"""
    SELECT Professeur, Semestre, Filiere, Groupe, Jour, Lheure, Salle
    FROM MasterSchedule
    WHERE Jour = ? 
    AND Lheure = ? 
    AND Salle IN ({placeholders})
    """
    
    # The values passed to the query: the target day, the time slot, and the list of empty rooms
    query_values = [target_jour, time_slot] + empty_rooms
    
    absent_classes = cursor.execute(query, query_values).fetchall()

    # 4. Record the Absences in the AbsenceRecords table
    recorded_count = 0
    for row in absent_classes:
        insert_query = """
        INSERT INTO AbsenceRecords 
        (date_absent, Professeur, Semestre, Filiere, Groupe, Jour, Lheure, Salle, absence_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        insert_values = [
            input_date, row['Professeur'], row['Semestre'], row['Filiere'], row['Groupe'], 
            row['Jour'], row['Lheure'], row['Salle'], 'Salle Vide (Rapport du Gardien)'
        ]
        cursor.execute(insert_query, insert_values)
        recorded_count += 1
    
    db.commit()
    
    return redirect(url_for('success_page', recorded=recorded_count))

@app.route('/success')
def success_page():
    recorded_count = request.args.get('recorded', 0)
    return f"<h1>Succès!</h1><p>{recorded_count} absences enregistrées. <a href='/dashboard'>Voir le Tableau de Bord</a> ou <a href='/'>Enregistrer Plus</a></p>"


# --- Search Route ---

@app.route('/search_schedule', methods=['GET', 'POST'])
def search_schedule():
    db = get_db()
    results = None
    query_term = ""

    if request.method == 'POST':
        query_term = request.form.get('query_term', '').strip()
        
        # Search for scheduled classes AND recorded absences containing the term
        search_query = """
        SELECT * FROM MasterSchedule 
        WHERE Professeur LIKE ? OR Salle LIKE ?
        LIMIT 50
        """
        # The % allows for partial matching (e.g., searching "MARIE" finds "MARIE-ANNE")
        search_param = '%' + query_term + '%'
        
        # Fetching schedule results
        schedule_results = db.execute(search_query, (search_param, search_param)).fetchall()

        # Fetching absence results
        absence_query = """
        SELECT * FROM AbsenceRecords 
        WHERE Professeur LIKE ? OR Salle LIKE ?
        ORDER BY date_absent DESC
        LIMIT 50
        """
        absence_results = db.execute(absence_query, (search_param, search_param)).fetchall()

        results = {
            'schedule': schedule_results,
            'absences': absence_results
        }

    return render_template('search.html', results=results, query_term=query_term)

# --- Dashboard Route ---
@app.route('/dashboard')
def dashboard():
    """Generates and displays key statistics from AbsenceRecords."""
    db = get_db()
    
    # Query 1: Top 10 Absent Professors
    top_profs_query = """
    SELECT Professeur, COUNT(id) as total_absences
    FROM AbsenceRecords
    GROUP BY Professeur
    ORDER BY total_absences DESC
    LIMIT 10
    """
    top_profs = db.execute(top_profs_query).fetchall()

    # Query 2: Top 10 Absent Modules (Filiere)
    top_modules_query = """
    SELECT Filiere, COUNT(id) as total_absences
    FROM AbsenceRecords
    GROUP BY Filiere
    ORDER BY total_absences DESC
    LIMIT 10
    """
    top_modules = db.execute(top_modules_query).fetchall()
    
    # Query 3: Absences per Day of the Week
    absences_by_day_query = """
    SELECT Jour, COUNT(id) as total_absences
    FROM AbsenceRecords
    GROUP BY Jour
    ORDER BY total_absences DESC
    """
    absences_by_day = db.execute(absences_by_day_query).fetchall()

    return render_template('dashboard.html', 
                           top_profs=top_profs, 
                           top_modules=top_modules, 
                           absences_by_day=absences_by_day)

if __name__ == '__main__':
    # Setting debug=True restarts the server automatically when you save changes
    app.run(debug=True)