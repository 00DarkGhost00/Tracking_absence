import pandas as pd
import sqlite3

def restore():
    conn = sqlite3.connect('absence_tracker.db')
    try:
        df = pd.read_csv('Absence.csv', sep=';', encoding='latin-1')
        df.columns = df.columns.str.strip()
        df = df.rename(columns={'Date': 'date_absent', 'Filiére': 'Filiere', 'FiliÃ©re': 'Filiere'})
        df['date_absent'] = pd.to_datetime(df['date_absent'], dayfirst=True).dt.strftime('%Y-%m-%d')
        df.to_sql('AbsenceRecords', conn, if_exists='append', index=False)
        print(f"✅ Restored {len(df)} absences!")
    except Exception as e: print(f"❌ Error: {e}")
    finally: conn.close()

if __name__ == '__main__': restore()