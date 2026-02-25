import sqlite3
import pandas as pd

def fix_everything():
    file_path = 'sql22.csv'
    db_path = 'absence_tracker.db'
    
    try:
        # 1. Lecture avec le bon séparateur (;) et le bon encodage pour l'arabe
        df = pd.read_csv(file_path, sep=';', encoding='utf-8-sig')
        
        # 2. Nettoyage des noms de colonnes
        df.columns = [c.strip() for c in df.columns]
        
        # 3. Normalisation des noms (ex: groupe -> Groupe)
        # On s'assure que les colonnes vitales sont là
        mapping = {
            'groupe': 'Groupe',
            'Filiere': 'Filiere',
            'Professeur': 'Professeur',
            'Module': 'Module'
        }
        df.rename(columns=mapping, inplace=True)
        
        # 4. Remplir les cases vides dans Groupe si nécessaire
        if 'Groupe' in df.columns:
            df['Groupe'] = df['Groupe'].fillna('G1')
        else:
            df['Groupe'] = 'G1'

        # 5. Connexion et sauvegarde
        conn = sqlite3.connect(db_path)
        
        # On écrase la table MasterSchedule avec les données propres
        df.to_sql('MasterSchedule', conn, if_exists='replace', index=False)
        
        # Vérification rapide de la table des absences (pour ne pas avoir l'erreur de tout à l'heure)
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE AbsenceRecords ADD COLUMN Module TEXT DEFAULT ''")
        except:
            pass # Déjà là
            
        try:
            cursor.execute("ALTER TABLE AbsenceRecords ADD COLUMN absence_reason TEXT DEFAULT 'Non justifiée'")
        except:
            pass # Déjà là

        conn.commit()
        conn.close()
        
        print("✅ TOUT EST RÉPARÉ !")
        print(f"--- {len(df)} cours importés.")
        print(f"--- Colonnes : {list(df.columns)}")
        print("--- L'arabe est maintenant correctement encodé.")

    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    fix_everything()