import pandas as pd
import sqlite3

DATABASE_NAME = 'absence_tracker.db'
# NOTE: Using the new file name that has the semicolon delimiter
CSV_FILE = 'Database.csv' 

def load_master_schedule():
    """Reads the CSV and inserts data into the MasterSchedule table."""
    try:
        # 1. Read the CSV file using pandas.
        # FIX: We specify both the encoding ('latin-1') and the semicolon delimiter (sep=';').
        df = pd.read_csv(CSV_FILE, encoding='latin-1', sep=';')

        # --- ROBUST COLUMN CLEANING STEP ---
        # 2. Normalize column names: strip whitespace and convert to lowercase
        df.columns = df.columns.str.strip().str.lower()
        
        # 3. Rename columns to match the standardized database fields (e.g., removing the accent)
        # We assume the column with the accent is 'filiére'
        df = df.rename(columns={'filiére': 'filiere'})
        
        # -----------------------------------

        # 4. Clean data: Replace missing group names with an empty string
        df['groupe'] = df['groupe'].fillna('')
        
        # 5. Connect to the database
        conn = sqlite3.connect(DATABASE_NAME)
        
        # 6. Prepare data for insertion (selecting and ordering columns)
        data_to_insert = df[[
            'professeur', 'semestre', 'filiere', 'groupe', 
            'jour', 'lheure', 'salle'
        ]]

        # Rename columns back to the exact casing used in the database table definition 
        data_to_insert.columns = [
            'Professeur', 'Semestre', 'Filiere', 'Groupe', 
            'Jour', 'Lheure', 'Salle'
        ]

        data_to_insert.to_sql(
            'MasterSchedule', 
            conn, 
            if_exists='replace', 
            index=False 
        )

        conn.close()
        print(f"Successfully loaded {len(df)} records into MasterSchedule.")
        
    except FileNotFoundError:
        print(f"ERROR: The file {CSV_FILE} was not found. Please ensure the file is named 'Database.csv' in your project folder.")
    except Exception as e:
        print(f"An error occurred during ingestion: {e}")


if __name__ == '__main__':
    load_master_schedule()