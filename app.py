from datetime import datetime, timedelta
import io
import os
import sqlite3
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
import base64
import json

# --- CLÉ API GEMINI INTÉGRÉE ---
CLE_API_GEMINI_FIXE = "AQ.Ab8RN6KIbYbIZWL5lJUe0rE_tL6Vn8OHWbU0toaV2ZoF97RX_A"

# Configuration de la page
st.set_page_config(
    page_title="StockEasy - Gestion de Stock", page_icon="📦", layout="wide"
)

# --- DESIGN & ESTHÉTIQUE ÉPURÉE ---
st.markdown("""
    <style>
    .stApp {
        background-color: #F8F9FA;
        color: #1F2937;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    h1, h2, h3 {
        color: #111827 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-weight: 700;
    }
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E5E7EB;
    }
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p {
        color: #374151 !important;
    }
    div.stRadio > div {
        gap: 10px;
    }
    div.stRadio > div label {
        background-color: #F3F4F6;
        padding: 10px 14px;
        border-radius: 10px;
        border: 1px solid #E5E7EB;
        width: 100%;
        cursor: pointer;
        transition: all 0.2s ease-in-out;
    }
    div.stRadio > div label:hover {
        background-color: #E5E7EB;
        border-color: #D1D5DB;
    }
    .stButton>button {
        background-color: #1F2937;
        color: #FFFFFF !important;
        border-radius: 8px;
        border: none;
        padding: 0.5rem 1rem;
        font-weight: 600;
    }
    .stButton>button p {
        color: #FFFFFF !important;
    }
    .stButton>button:hover {
        background-color: #374151;
        color: #FFFFFF !important;
    }
    [data-testid="stMetricValue"] {
        color: #111827 !important;
        font-weight: 700;
    }
    [data-testid="stMetricLabel"] {
        color: #6B7280 !important;
    }
    [data-testid="stDataFrame"] {
        background-color: #FFFFFF;
        border-radius: 8px;
        border: 1px solid #E5E7EB;
    }
    </style>
""", unsafe_allow_html=True)

# Dossiers locaux
DOSSIER_FACTURES = "factures_archives"
if not os.path.exists(DOSSIER_FACTURES):
    os.makedirs(DOSSIER_FACTURES)

DOSSIER_CATALOGUES = "catalogues_fournisseurs"
if not os.path.exists(DOSSIER_CATALOGUES):
    os.makedirs(DOSSIER_CATALOGUES)

# --- BASE DE DONNÉES ---
def init_db():
    try:
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()

            cursor.execute("CREATE TABLE IF NOT EXISTS fournisseurs (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT UNIQUE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS produits (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, categorie TEXT, contenance TEXT, fournisseur TEXT, prix_unitaire REAL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS catalogues_fichiers (id INTEGER PRIMARY KEY AUTOINCREMENT, fournisseur TEXT UNIQUE, fichier_path TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS factures (id INTEGER PRIMARY KEY AUTOINCREMENT, date_facture TEXT, fournisseur TEXT, montant_total REAL, fichier_path TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS lignes_facture (id INTEGER PRIMARY KEY AUTOINCREMENT, facture_id INTEGER, produit TEXT, categorie TEXT, contenance TEXT, quantite REAL, prix_unitaire REAL, total_ligne REAL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS commandes (id INTEGER PRIMARY KEY AUTOINCREMENT, date_commande TEXT, fournisseur TEXT, produit TEXT, contenance TEXT, type_commande TEXT, quantite_commandee REAL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS receptions (id INTEGER PRIMARY KEY AUTOINCREMENT, date_reception TEXT, fournisseur TEXT, produit TEXT, quantite_recue REAL, statut TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS reclamations (id INTEGER PRIMARY KEY AUTOINCREMENT, date_reception TEXT, fournisseur TEXT, produit TEXT, type_commande TEXT, quantite_commandee REAL, quantite_recue REAL, ecart REAL, statut TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS inventaires_archives (id INTEGER PRIMARY KEY AUTOINCREMENT, date_inventaire TEXT, mode TEXT, valeur_totale REAL, details_json TEXT)")

            try:
                cursor.execute("ALTER TABLE factures ADD COLUMN fichier_path TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE commandes ADD COLUMN type_commande TEXT")
            except sqlite3.OperationalError:
                pass
            
            conn.commit()
    except Exception as e:
        print(f"Erreur init_db: {e}")

init_db()

# --- GESTION DE LA CONNEXION ---
if "connecte" not in st.session_state:
    st.session_state.connecte = False
if "utilisateur" not in st.session_state:
    st.session_state.utilisateur = ""

UTILISATEURS_AUTORISES = {
    "adminmassi": "Babouche2000",
    "adminceline": "Céline05!",
    "adminnico": "Winnie01?"
}

if not st.session_state.connecte:
    st.title("🔐 StockEasy - Connexion")
    st.markdown("Veuillez vous identifier pour accéder au logiciel.")
    
    with st.form("form_connexion"):
        username_input = st.text_input("Identifiant")
        password_input = st.text_input("Mot de passe", type="password")
        submit_login = st.form_submit_button("Se connecter", type="primary")
        
        if submit_login:
            if username_input in UTILISATEURS_AUTORISES and UTILISATEURS_AUTORISES[username_input] == password_input:
                st.session_state.connecte = True
                st.session_state.utilisateur = username_input
                st.success("Connexion réussie ! Chargement...")
                st.rerun()
            else:
                st.error("❌ Identifiant ou mot de passe incorrect.")
    
    st.stop()

# --- CODE PRINCIPAL (ACCESSIBLE APRÈS CONNEXION) ---

CATEGORIES = [
    "Vaisselle, consommable & emballage snack",
    "Salé, féculents & conserves",
    "Sauces, huiles & vinaigres",
    "Épices & Condiments",
    "Snack frais",
    "Snack surgelés",
    "Produits d'entretiens",
    "Boissons Softs",
    "Bières",
    "Alcools & Spiritueux",
    "Vins & Champagne",
    "Café & Thé",
    "Sucres divers",
]

def nettoyer_et_mapper_categorie(cat_brute):
    if not cat_brute or pd.isna(cat_brute):
        return "Boissons Softs"
    cat_str = str(cat_brute).strip()
    if cat_str in CATEGORIES:
        return cat_str
    for cat in CATEGORIES:
        if cat_str.lower() == cat.lower():
            return cat
            
    cat_lower = cat_str.lower()
    if "alcool" in cat_lower or "spiritueux" in cat_lower:
        return "Alcools & Spiritueux"
    elif "bière" in cat_lower or "biere" in cat_lower:
        return "Bières"
    elif "vin" in cat_lower or "champagne" in cat_lower:
        return "Vins & Champagne"
    elif "soft" in cat_lower or "boisson" in cat_lower or "soda" in cat_lower:
        return "Boissons Softs"
    elif "café" in cat_lower or "cafe" in cat_lower or "thé" in cat_lower or "the" in cat_lower:
        return "Café & Thé"
    elif "sucre" in cat_lower:
        return "Sucres divers"
    elif "entretien" in cat_lower or "nettoyage" in cat_lower:
        return "Produits d'entretiens"
    elif "frais" in cat_lower:
        return "Snack frais"
    elif "surgelé" in cat_lower or "surgele" in cat_lower:
        return "Snack surgelés"
    elif "sauce" in cat_lower or "huile" in cat_lower or "vinaigre" in cat_lower:
        return "Sauces, huiles & vinaigres"
    elif "sel" in cat_lower or "epice" in cat_lower or "condiment" in cat_lower:
        return "Épices & Condiments"
    elif "salé" in cat_lower or "conserve" in cat_lower or "féculent" in cat_lower:
        return "Salé, féculents & conserves"
    elif "vaisselle" in cat_lower or "emballage" in cat_lower or "consommable" in cat_lower:
        return "Vaisselle, consommable & emballage snack"
    return "Boissons Softs"

def get_polaire_activite(categorie):
    categories_bar = [
        "Boissons Softs",
        "Bières",
        "Alcools & Spiritueux",
        "Vins & Champagne",
        "Café & Thé",
    ]
    if categorie in categories_bar:
        return "🍺 Bar"
    else:
        return "🍳 Cuisine / Snack"

def upsert_produit(cursor, nom, categorie, contenance, fournisseur, prix_unitaire):
    cursor.execute("SELECT id FROM produits WHERE nom = ? AND fournisseur = ?", (nom, fournisseur))
    res = cursor.fetchone()
    if res:
        cursor.execute("""
            UPDATE produits SET categorie = ?, contenance = ?, prix_unitaire = ?
            WHERE nom = ? AND fournisseur = ?
        """, (categorie, contenance, prix_unitaire, nom, fournisseur))
    else:
        cursor.execute("""
            INSERT INTO produits (nom, categorie, contenance, fournisseur, prix_unitaire)
            VALUES (?, ?, ?, ?, ?)
        """, (nom, categorie, contenance, fournisseur, prix_unitaire))

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=120)
    else:
        st.markdown("### 📦 StockEasy")
    
    st.markdown("---")
    st.markdown(f"👤 Connecté : **{st.session_state.utilisateur}**")
    if st.button("Se déconnecter"):
        st.session_state.connecte = False
        st.session_state.utilisateur = ""
        st.rerun()

    st.markdown("---")
    st.markdown("### 🧭 Navigation")
    
    menu = [
        "Tableau de bord",
        "Fournisseurs & Catalogues",
        "Saisie des factures",
        "Inventaire & Valorisation",
        "Passer une commande",
        "Réception & Contrôle",
        "Réclamations & Écarts",
        "Archives & Historique",
    ]
    
    choix = st.radio("Navigation", menu, label_visibility="collapsed")

    if choix == "Passer une commande":
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_f = pd.read_sql_query("SELECT nom FROM fournisseurs", conn)
        fours_sidebar = df_f["nom"].tolist() if not df_f.empty else []
        
        st.markdown("---")
        st.markdown("### 🛒 Validation Commande")
        if fours_sidebar:
            st.session_state.sidebar_f_cmd = st.selectbox("Fournisseur cible", fours_sidebar, key="sel_sidebar_f_cmd")
        else:
            st.session_state.sidebar_f_cmd = ""
        
        st.session_state.sidebar_btn_cmd = st.button("Valider la commande", type="primary", key="btn_sidebar_cmd")

    st.markdown("---")
    st.caption("Session : Massi • BUT GEA GEMA")

# --- 1. TABLEAU DE BORD ---
if choix == "Tableau de bord":
    st.header("📊 Tableau de bord & Pilotage des Dépenses")
    
    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
        df_fac = pd.read_sql_query("SELECT * FROM factures", conn)
        df_lig = pd.read_sql_query("SELECT * FROM lignes_facture", conn)

    if df_fac.empty or df_lig.empty:
        st.info("ℹ️ Aucune donnée de dépense enregistrée pour le moment. Saisis des factures pour alimenter le tableau de bord.")
    else:
        df_lig = df_lig.merge(df_fac[["id", "date_facture", "fournisseur"]], left_on="facture_id", right_on="id", how="left")
        df_lig["date_facture"] = pd.to_datetime(df_lig["date_facture"], errors='coerce')
        df_lig["Pôle"] = df_lig["categorie"].apply(get_polaire_activite)

        st.markdown("### 🎛️ Filtres & Période d'analyse")
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            min_date = df_lig["date_facture"].min().date() if not df_lig["date_facture"].isna().all() else datetime.today().date()
            max_date = df_lig["date_facture"].max().date() if not df_lig["date_facture"].isna().all() else datetime.today().date()
            date_debut = st.date_input("Date de début", value=min_date)
        with col_f2:
            date_fin = st.date_input("Date de fin", value=max_date)
        with col_f3:
            poles_dispos = ["Tous", "🍺 Bar", "🍳 Cuisine / Snack"]
            filtre_pole = st.selectbox("Filtrer par pôle d'activité", poles_dispos)

        col_f4, col_f5 = st.columns(2)
        with col_f4:
            categories_dispos = ["Toutes"] + sorted(df_lig["categorie"].dropna().unique().tolist())
            filtre_cat = st.selectbox("Filtrer par catégorie de produit", categories_dispos)
        with col_f5:
            fournisseurs_dispos = ["Tous"] + sorted(df_lig["fournisseur"].dropna().unique().tolist())
            filtre_four = st.selectbox("Filtrer par fournisseur", fournisseurs_dispos)

        df_filtered = df_lig.copy()
        if date_debut and date_fin:
            df_filtered = df_filtered[(df_filtered["date_facture"].dt.date >= date_debut) & (df_filtered["date_facture"].dt.date <= date_fin)]
        if filtre_pole != "Tous":
            df_filtered = df_filtered[df_filtered["Pôle"] == filtre_pole]
        if filtre_cat != "Toutes":
            df_filtered = df_filtered[df_filtered["categorie"] == filtre_cat]
        if filtre_four != "Tous":
            df_filtered = df_filtered[df_filtered["fournisseur"] == filtre_four]

        st.divider()

        if df_filtered.empty:
            st.warning("⚠️ Aucune dépense ne correspond aux filtres sélectionnés.")
        else:
            tot_depenses = df_filtered["total_ligne"].sum()
            tot_bar = df_filtered[df_filtered["Pôle"] == "🍺 Bar"]["total_ligne"].sum()
            tot_snack = df_filtered[df_filtered["Pôle"] == "🍳 Cuisine / Snack"]["total_ligne"].sum()

            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("💶 Dépenses Totales (filtrées)", f"{tot_depenses:.2f} €")
            col_m2.metric("🍺 Dépenses Pôle Bar", f"{tot_bar:.2f} €", f"{(tot_bar/tot_depenses*100):.1f}%" if tot_depenses > 0 else "0%")
            col_m3.metric("🍳 Dépenses Pôle Cuisine / Snack", f"{tot_snack:.2f} €", f"{(tot_snack/tot_depenses*100):.1f}%" if tot_depenses > 0 else "0%")

            st.divider()

            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("#### 📊 Répartition des dépenses par Catégorie")
                df_cat_grp = df_filtered.groupby("categorie")["total_ligne"].sum().reset_index()
                df_cat_grp.columns = ["Catégorie", "Montant (€)"]
                st.bar_chart(df_cat_grp.set_index("Catégorie"))

            with col_g2:
                st.markdown("#### 📈 Évolution temporelle des dépenses")
                df_time_grp = df_filtered.groupby(df_filtered["date_facture"].dt.date)["total_ligne"].sum().reset_index()
                df_time_grp.columns = ["Date", "Montant (€)"]
                st.line_chart(df_time_grp.set_index("Date"))

            st.divider()

            st.markdown("#### 📋 Détail des lignes de dépenses")
            col_t1, col_t2 = st.columns([2, 2])
            with col_t1:
                colonne_tri = st.selectbox("Trier par", ["date_facture", "total_ligne", "produit", "fournisseur"], index=1)
            with col_t2:
                ordre_tri = st.radio("Ordre de tri", ["Croissant 📈", "Décroissant 📉"], horizontal=True)
            
            ascending_bool = True if "Croissant" in ordre_tri else False
            df_display = df_filtered.sort_values(by=colonne_tri, ascending=ascending_bool)

            df_display_clean = df_display[["date_facture", "fournisseur", "produit", "categorie", "Pôle", "quantite", "prix_unitaire", "total_ligne"]].copy()
            df_display_clean.columns = ["Date", "Fournisseur", "Produit", "Catégorie", "Pôle", "Quantité", "Prix Unit. (€)", "Total (€)"]
            df_display_clean["Date"] = pd.to_datetime(df_display_clean["Date"]).dt.strftime('%Y-%m-%d')

            st.dataframe(df_display_clean, use_container_width=True)

            csv_data = df_display_clean.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Exporter ce rapport de dépenses (CSV)",
                data=csv_data,
                file_name=f"rapport_depenses_{date_debut}_au_{date_fin}.csv",
                mime="text/csv"
            )

# --- 2. FOURNISSEURS & CATALOGUES ---
elif choix == "Fournisseurs & Catalogues":
    st.header("🏢 Gestion des Fournisseurs & Catalogues")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Fournisseurs", 
        "📋 Catalogues par Fournisseur", 
        "📥 Importer / Mettre à jour un Catalogue", 
        "🗑️ Supprimer un Catalogue",
        "🔐 Réinitialisation Sécurisée"
    ])

    with tab1:
        st.subheader("➕ Ajouter un nouveau fournisseur")
        nouveau_fournisseur = st.text_input("Nom du fournisseur")
        if st.button("Enregistrer le fournisseur"):
            if nouveau_fournisseur:
                try:
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO fournisseurs (nom) VALUES (?)", (nouveau_fournisseur.strip(),))
                        conn.commit()
                    st.success(f"Fournisseur '{nouveau_fournisseur}' ajouté avec succès !")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.warning("Ce fournisseur existe déjà.")
            else:
                st.error("Veuillez entrer un nom.")

        st.divider()
        st.subheader("🗑️ Supprimer un fournisseur")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fours_sup = pd.read_sql_query("SELECT nom FROM fournisseurs", conn)
        fours_sup = df_fours_sup["nom"].tolist() if not df_fours_sup.empty else []

        if fours_sup:
            four_a_supprimer = st.selectbox("Sélectionner le fournisseur à supprimer", fours_sup, key="sel_four_sup")
            if st.button("Supprimer ce fournisseur"):
                with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM fournisseurs WHERE nom = ?", (four_a_supprimer,))
                    cursor.execute("DELETE FROM produits WHERE fournisseur = ?", (four_a_supprimer,))
                    cursor.execute("DELETE FROM catalogues_fichiers WHERE fournisseur = ?", (four_a_supprimer,))
                    conn.commit()
                st.success(f"Fournisseur '{four_a_supprimer}' supprimé avec succès !")
                st.rerun()
        else:
            st.info("Aucun fournisseur enregistré.")

        st.divider()
        st.subheader("📋 Fournisseurs enregistrés")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fournisseurs = pd.read_sql_query("SELECT * FROM fournisseurs", conn)
        st.dataframe(df_fournisseurs, use_container_width=True)

    with tab2:
        st.subheader("📋 Catalogue dédié par Fournisseur")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fours_all = pd.read_sql_query("SELECT nom FROM fournisseurs", conn)

        fours_dispos = df_fours_all["nom"].tolist() if not df_fours_all.empty else []

        if not fours_dispos:
            st.info("ℹ️ Aucun fournisseur enregistré.")
        else:
            fournisseur_selectionne = st.selectbox("Sélectionner le fournisseur pour voir son tableau", fours_dispos, key="sel_vue_fournisseur")
            with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                df_prod_four = pd.read_sql_query(
                    "SELECT id, nom, categorie, contenance, prix_unitaire FROM produits WHERE fournisseur = ?",
                    conn,
                    params=(fournisseur_selectionne,)
                )
            if df_prod_four.empty:
                st.info(f"ℹ️ Aucun produit dans le catalogue de **{fournisseur_selectionne}**.")
            else:
                st.dataframe(df_prod_four, use_container_width=True)

    with tab3:
        st.subheader("📥 Importer ou Compléter un Catalogue Fournisseur")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fours_cat = pd.read_sql_query("SELECT nom FROM fournisseurs", conn)
        fours_catalogue = df_fours_cat["nom"].tolist() if not df_fours_cat.empty else []

        options_four = ["➕ Saisir un nouveau fournisseur..."] + fours_catalogue
        choix_four_import = st.selectbox("Fournisseur cible", options_four, key="sel_four_catalogue")

        if choix_four_import == "➕ Saisir un nouveau fournisseur...":
            fournisseur_cat = st.text_input("Nom du nouveau fournisseur", "").strip()
        else:
            fournisseur_cat = choix_four_import

        fichier_catalogue = st.file_uploader("Fichier catalogue (Excel ou CSV)", type=["csv", "xlsx"], key="uploader_catalogue")

        if fichier_catalogue is not None:
            if "dernier_fichier_lu" not in st.session_state or st.session_state.dernier_fichier_lu != fichier_catalogue.name:
                try:
                    if fichier_catalogue.name.endswith('.csv'):
                        try:
                            df_lu = pd.read_csv(fichier_catalogue)
                            if len(df_lu.columns) <= 1:
                                fichier_catalogue.seek(0)
                                df_lu = pd.read_csv(fichier_catalogue, sep=';')
                        except Exception:
                            fichier_catalogue.seek(0)
                            df_lu = pd.read_csv(fichier_catalogue, sep=';', encoding='latin1')
                    else:
                        df_lu = pd.read_excel(fichier_catalogue)
                    
                    df_lu.columns = [str(c).lower().strip() for c in df_lu.columns]
                    col_nom = next((c for c in df_lu.columns if "nom" in c or "produit" in c), df_lu.columns[0])
                    col_cat = next((c for c in df_lu.columns if "cat" in c), None)
                    col_cont = next((c for c in df_lu.columns if "cont" in c), None)
                    col_prix = next((c for c in df_lu.columns if "prix" in c), None)

                    data_prepa = []
                    for _, r in df_lu.iterrows():
                        n = str(r.get(col_nom, "")).strip()
                        if not n or n.lower() == "nan": continue
                        c = nettoyer_et_mapper_categorie(r.get(col_cat, "Boissons Softs") if col_cat else "Boissons Softs")
                        co = str(r.get(col_cont, "Unite")).strip()
                        try:
                            p = float(str(r.get(col_prix, 0.0)).replace(',', '.'))
                        except:
                            p = 0.0
                        data_prepa.append({"Produit": n, "Catégorie": c, "Contenance": co, "Prix Unitaire (€)": p})

                    st.session_state.df_catalogue_en_cours = pd.DataFrame(data_prepa)
                    st.session_state.dernier_fichier_lu = fichier_catalogue.name
                except Exception as err:
                    st.error(f"⚠️ Erreur de lecture : {err}")

        if "df_catalogue_en_cours" in st.session_state and not st.session_state.df_catalogue_en_cours.empty:
            edited_preview_df = st.data_editor(st.session_state.df_catalogue_en_cours, num_rows="dynamic", use_container_width=True, key="editor_catalogue_import")

            if st.button("💾 Ajouter / Mettre à jour le catalogue", type="primary"):
                if not fournisseur_cat or not fournisseur_cat.strip():
                    st.error("❌ Nom de fournisseur invalide.")
                else:
                    fournisseur_final = fournisseur_cat.strip()
                    try:
                        path_sauvegarde = None
                        if fichier_catalogue is not None:
                            nom_propre = fournisseur_final.replace(" ", "_").lower()
                            path_sauvegarde = os.path.join(DOSSIER_CATALOGUES, f"catalogue_{nom_propre}_{datetime.today().strftime('%Y%m%d_%H%M%S')}{os.path.splitext(fichier_catalogue.name)[1]}")
                            with open(path_sauvegarde, "wb") as f_out:
                                f_out.write(fichier_catalogue.getbuffer())

                        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                            cursor = conn.cursor()
                            cursor.execute("INSERT OR IGNORE INTO fournisseurs (nom) VALUES (?)", (fournisseur_final,))
                            
                            for _, r in edited_preview_df.iterrows():
                                prod_nom = str(r["Produit"]).strip()
                                if prod_nom:
                                    cat_prod = nettoyer_et_mapper_categorie(r["Catégorie"])
                                    cont_prod = str(r["Contenance"]).strip()
                                    try:
                                        prix_prod = float(str(r["Prix Unitaire (€)"]).replace(',', '.'))
                                    except:
                                        prix_prod = 0.0
                                    
                                    upsert_produit(cursor, prod_nom, cat_prod, cont_prod, fournisseur_final, prix_prod)

                            if path_sauvegarde:
                                cursor.execute("INSERT OR REPLACE INTO catalogues_fichiers (fournisseur, fichier_path) VALUES (?, ?)", (fournisseur_final, path_sauvegarde))
                            conn.commit()

                        if "df_catalogue_en_cours" in st.session_state: del st.session_state.df_catalogue_en_cours
                        if "dernier_fichier_lu" in st.session_state: del st.session_state.dernier_fichier_lu
                        st.success(f"🎉 Catalogue de **{fournisseur_final}** mis à jour et complété avec succès !")
                        st.rerun()
                    except Exception as err:
                        st.error(f"❌ Erreur : {err}")

    with tab4:
        st.subheader("🗑️ Supprimer un catalogue")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fours_prod = pd.read_sql_query("SELECT DISTINCT fournisseur FROM produits", conn)
        fours_avec_produits = df_fours_prod["fournisseur"].tolist() if not df_fours_prod.empty else []
        if fours_avec_produits:
            fournisseur_a_vider = st.selectbox("Sélectionner", fours_avec_produits, key="sel_four_vider")
            if st.button("Supprimer tout le catalogue", type="primary"):
                with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM produits WHERE fournisseur = ?", (fournisseur_a_vider,))
                    cursor.execute("DELETE FROM catalogues_fichiers WHERE fournisseur = ?", (fournisseur_a_vider,))
                    conn.commit()
                st.success("Catalogue supprimé !")
                st.rerun()
        else:
            st.info("Aucun catalogue.")

    with tab5:
        st.subheader("🔐 Remise à zéro complète")
        with st.form("form_reset_commandes"):
            identifiant_admin = st.text_input("Identifiant")
            mot_de_passe_admin = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Tout effacer"):
                if identifiant_admin == "adminmassi" and mot_de_passe_admin == "Babouche2000":
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        for table in ["commandes", "receptions", "reclamations", "factures", "lignes_facture", "produits", "catalogues_fichiers", "inventaires_archives"]:
                            conn.execute(f"DELETE FROM {table}")
                        conn.commit()
                    st.success("Remise à zéro effectuée !")
                    st.rerun()
                else:
                    st.error("Identifiants incorrects.")

# --- 3. SAISIE DES FACTURES ---
elif choix == "Saisie des factures":
    st.header("🧾 Saisie et Archivage de Facture")
    
    col_up1, col_up2 = st.columns(2)
    with col_up1:
        fichier_facture = st.file_uploader("Fichier facture (PDF / Image)", type=["pdf", "png", "jpg", "jpeg"])
    with col_up2:
        if fichier_facture:
            st.markdown("### 👁️ Aperçu du document")
            if fichier_facture.type in ["image/png", "image/jpeg"]:
                st.image(fichier_facture, use_container_width=True)
            elif fichier_facture.type == "application/pdf":
                base64_pdf = base64.b64encode(fichier_facture.getvalue()).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="350px" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)

    mode_saisie = st.radio("Mode de saisie", ["✍️ Saisie Interactive", "🤖 Analyse & Extraction IA (Gemini)"], horizontal=True)

    if mode_saisie == "🤖 Analyse & Extraction IA (Gemini)":
        st.markdown("### 🧠 Extraction automatique par Gemini (Modèle 3.8 Flash)")
        
        if st.button("Lancer l'analyse de la facture"):
            if not fichier_facture:
                st.warning("Veuillez d'abord importer un fichier de facture.")
            else:
                with st.spinner("Analyse du document avec Gemini 3.8 Flash en cours..."):
                    try:
                        client = genai.Client(api_key=CLE_API_GEMINI_FIXE)
                        bytes_data = fichier_facture.getvalue()
                        
                        prompt_ia = (
                            "Analyse cette facture et extrait les informations suivantes au format JSON strict : "
                            "{\"fournisseur\": \"nom du fournisseur\", "
                            "\"date_facture\": \"AAAA-MM-JJ\", "
                            "\"lignes\": ["
                            "{\"produit\": \"nom\", \"categorie\": \"catégorie parmi Vaisselle, consommable & emballage snack / Salé, féculents & conserves / Sauces, huiles & vinaigres / Épices & Condiments / Snack frais / Snack surgelés / Produits d'entretiens / Boissons Softs / Bières / Alcools & Spiritueux / Vins & Champagne / Café & Thé / Sucres divers\", \"contenance\": \"unité ou format\", \"quantite\": 1.0, \"prix_unitaire\": 0.0}"
                            "]}"
                        )
                        
                        part_file = types.Part.from_bytes(
                            data=bytes_data,
                            mime_type=fichier_facture.type,
                        )
                        
                        response = client.models.generate_content(
                            model='gemini-3.8-flash',
                            contents=[prompt_ia, part_file]
                        )
                        
                        texte_resp = response.text.strip()
                        if "```json" in texte_resp:
                            texte_resp = texte_resp.split("```json")[1].split("```")[0].strip()
                        elif "```" in texte_resp:
                            texte_resp = texte_resp.split("```")[1].split("```")[0].strip()
                            
                        data_ia = json.loads(texte_resp)
                        st.session_state.ia_fournisseur = data_ia.get("fournisseur", "")
                        st.session_state.ia_date = data_ia.get("date_facture", str(datetime.today().date()))
                        st.session_state.ia_lignes = data_ia.get("lignes", [])
                        st.success("✅ Analyse réussie avec Gemini 3.8 Flash ! Vérifie et valide ci-dessous.")
                    except Exception as e:
                        st.error(f"Erreur lors de l'analyse IA : {e}")

        if "ia_lignes" in st.session_state and st.session_state.ia_lignes:
            st.markdown("### 📋 Résultats de l'extraction")
            f_s = st.text_input("Fournisseur détecté", value=st.session_state.get("ia_fournisseur", ""))
            try:
                d_fact = datetime.strptime(st.session_state.get("ia_date", str(datetime.today().date())), "%Y-%m-%d").date()
            except:
                d_fact = datetime.today().date()
            
            df_ia = pd.DataFrame(st.session_state.ia_lignes)
            if "produit" in df_ia.columns:
                df_ia = df_ia.rename(columns={"produit": "Produit", "categorie": "Catégorie", "contenance": "Contenance", "quantite": "Quantité", "prix_unitaire": "Prix Unitaire (€)"})
            
            ed_f_ia = st.data_editor(df_ia, num_rows="dynamic", use_container_width=True, key="editor_ia")
            
            if st.button("💾 Enregistrer la facture extraite par IA"):
                p_svg = None
                if fichier_facture:
                    p_svg = os.path.join(DOSSIER_FACTURES, f"{datetime.today().strftime('%Y%m%d_%H%M%S')}_{fichier_facture.name}")
                    with open(p_svg, "wb") as f_out: f_out.write(fichier_facture.getbuffer())
                
                tot_fact = (ed_f_ia["Quantité"] * ed_f_ia["Prix Unitaire (€)"]).sum() if not ed_f_ia.empty else 0.0
                with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                    cur = conn.cursor()
                    cur.execute("INSERT OR IGNORE INTO fournisseurs (nom) VALUES (?)", (f_s,))
                    cur.execute("INSERT INTO factures (date_facture, fournisseur, montant_total, fichier_path) VALUES (?, ?, ?, ?)",
                                (str(d_fact), f_s, float(tot_fact), p_svg))
                    f_id = cur.lastrowid
                    for _, r in ed_f_ia.iterrows():
                        prod_nom = str(r["Produit"]).strip()
                        if prod_nom:
                            cat_prod = nettoyer_et_mapper_categorie(r["Catégorie"])
                            cont_prod = str(r["Contenance"]).strip()
                            prix_prod = float(r["Prix Unitaire (€)"])
                            
                            cur.execute("INSERT INTO lignes_facture (facture_id, produit, categorie, contenance, quantite, prix_unitaire, total_ligne) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                        (f_id, prod_nom, cat_prod, cont_prod, float(r["Quantité"]), prix_prod, float(r["Quantité"])*prix_prod))
                            
                            upsert_produit(cur, prod_nom, cat_prod, cont_prod, f_s, prix_prod)
                    conn.commit()
                st.success("Facture enregistrée et catalogue fournisseur mis à jour / complété avec succès !")
                del st.session_state.ia_lignes
                st.rerun()

    else:
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_f = pd.read_sql_query("SELECT nom FROM fournisseurs", conn)
            df_prods_all = pd.read_sql_query("SELECT DISTINCT nom, categorie, contenance, prix_unitaire FROM produits", conn)

        fours = df_f["nom"].tolist() if not df_f.empty else []
        
        f_s = st.selectbox("Fournisseur", fours if fours else [""], key="s_f_fact")
        n_f = st.text_input("Ou nouveau fournisseur").strip()
        if n_f: f_s = n_f
        
        d_fact = st.date_input("Date", value=datetime.today())

        st.markdown("---")
        st.markdown("### 📝 Lignes de la facture")
        st.info("💡 **Astuce** : Sélectionne un produit existant dans la liste déroulante pour le pré-remplir, ou écris directement un nouveau nom. La catégorie utilise une liste déroulante stricte.")

        if "lignes_saisie" not in st.session_state:
            st.session_state.lignes_saisie = [
                {"produit": "", "categorie": CATEGORIES[0], "contenance": "1", "quantite": 1.0, "prix_unitaire": 0.0}
            ]

        produits_existants = [""] + df_prods_all["nom"].tolist() if not df_prods_all.empty else [""]

        lignes_a_supprimer = []
        for idx, ligne in enumerate(st.session_state.lignes_saisie):
            col_p1, col_p2, col_p3, col_p4, col_p5, col_p6 = st.columns([3, 3, 2, 1, 2, 1])

            with col_p1:
                choix_prod = st.selectbox(f"Produit #{idx+1}", produits_existants, index=produits_existants.index(ligne["produit"]) if ligne["produit"] in produits_existants else 0, key=f"sel_prod_{idx}")
                saisie_libre = st.text_input(f"Ou nouveau produit #{idx+1}", value=ligne["produit"] if choix_prod == "" else "", key=f"txt_prod_{idx}")
                
                prod_final = saisie_libre.strip() if saisie_libre.strip() else choix_prod
                ligne["produit"] = prod_final

                if choix_prod and not saisie_libre.strip() and not df_prods_all.empty:
                    p_info = df_prods_all[df_prods_all["nom"] == choix_prod]
                    if not p_info.empty:
                        ligne["categorie"] = p_info.iloc[0]["categorie"]
                        ligne["contenance"] = str(p_info.iloc[0]["contenance"])
                        ligne["prix_unitaire"] = float(p_info.iloc[0]["prix_unitaire"])

            with col_p2:
                cat_index = CATEGORIES.index(ligne["categorie"]) if ligne["categorie"] in CATEGORIES else 0
                ligne["categorie"] = st.selectbox("Catégorie", CATEGORIES, index=cat_index, key=f"sel_cat_{idx}")

            with col_p3:
                ligne["contenance"] = st.text_input("Contenance", value=str(ligne["contenance"]), key=f"txt_cont_{idx}")

            with col_p4:
                ligne["quantite"] = st.number_input("Qté", min_value=0.0, value=float(ligne["quantite"]), step=1.0, key=f"num_qte_{idx}")

            with col_p5:
                ligne["prix_unitaire"] = st.number_input("Prix U. (€)", min_value=0.0, value=float(ligne["prix_unitaire"]), step=0.01, format="%.2f", key=f"num_prix_{idx}")

            with col_p6:
                st.write("")
                if st.button("🗑️", key=f"del_ligne_{idx}"):
                    lignes_a_supprimer.append(idx)

        if lignes_a_supprimer:
            for i in sorted(lignes_a_supprimer, reverse=True):
                st.session_state.lignes_saisie.pop(i)
            st.rerun()

        col_b1, col_b2 = st.columns([1, 4])
        with col_b1:
            if st.button("➕ Ajouter une ligne"):
                st.session_state.lignes_saisie.append({"produit": "", "categorie": CATEGORIES[0], "contenance": "1", "quantite": 1.0, "prix_unitaire": 0.0})
                st.rerun()

        st.divider()

        if st.button("💾 Enregistrer la facture", type="primary"):
            if not f_s:
                st.error("❌ Veuillez préciser ou sélectionner un fournisseur.")
            else:
                lignes_valides = []
                doublon_detecte = False
                lignes_vues = set()

                for l in st.session_state.lignes_saisie:
                    p_nom = l["produit"].strip()
                    if p_nom:
                        cle_doublon = (p_nom.lower(), l["categorie"].lower(), str(l["contenance"]).lower(), float(l["prix_unitaire"]))
                        if cle_doublon in lignes_vues:
                            doublon_detecte = True
                            st.warning(f"⚠️ Doublon détecté pour le produit **{p_nom}** (même catégorie, contenance et prix).")
                        else:
                            lignes_vues.add(cle_doublon)
                            lignes_valides.append(l)

                if doublon_detecte:
                    st.error("❌ Impossible d'enregistrer : la facture contient des lignes strictement identiques (doublons).")
                elif not lignes_valides:
                    st.error("❌ Veuillez saisir au moins un produit valide.")
                else:
                    p_svg = None
                    if fichier_facture:
                        p_svg = os.path.join(DOSSIER_FACTURES, f"{datetime.today().strftime('%Y%m%d_%H%M%S')}_{fichier_facture.name}")
                        with open(p_svg, "wb") as f_out: f_out.write(fichier_facture.getbuffer())
                    
                    tot_fact = sum(float(item["quantite"]) * float(item["prix_unitaire"]) for item in lignes_valides)

                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        cur = conn.cursor()
                        cur.execute("INSERT OR IGNORE INTO fournisseurs (nom) VALUES (?)", (f_s,))
                        cur.execute("INSERT INTO factures (date_facture, fournisseur, montant_total, fichier_path) VALUES (?, ?, ?, ?)",
                                    (str(d_fact), f_s, float(tot_fact), p_svg))
                        f_id = cur.lastrowid
                        
                        for item in lignes_valides:
                            prod_nom = item["produit"]
                            cat_prod = item["categorie"]
                            cont_prod = str(item["contenance"])
                            qte = float(item["quantite"])
                            prix_prod = float(item["prix_unitaire"])
                            total_l = qte * prix_prod
                            
                            cur.execute("INSERT INTO lignes_facture (facture_id, produit, categorie, contenance, quantite, prix_unitaire, total_ligne) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                        (f_id, prod_nom, cat_prod, cont_prod, qte, prix_prod, total_l))
                            
                            upsert_produit(cur, prod_nom, cat_prod, cont_prod, f_s, prix_prod)
                        conn.commit()

                    st.success("🎉 Facture enregistrée avec succès et catalogue fournisseur mis à jour !")
                    st.session_state.lignes_saisie = [{"produit": "", "categorie": CATEGORIES[0], "contenance": "1", "quantite": 1.0, "prix_unitaire": 0.0}]
                    st.rerun()

# --- 4. INVENTAIRE & VALORISATION ---
elif choix == "Inventaire & Valorisation":
    st.header("📊 Réalisation de l'Inventaire & Chiffrage du Stock")
    st.write("Réalise ton inventaire global ou par fournisseur. Tu peux également exporter la feuille de comptage pour impression.")

    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
        df_fours_inv = pd.read_sql_query("SELECT DISTINCT fournisseur FROM produits", conn)
    fours_avec_catalogue = df_fours_inv["fournisseur"].tolist() if not df_fours_inv.empty else []

    col_inv1, col_inv2, col_inv3 = st.columns([2, 2, 2])
    with col_inv1:
        type_inventaire = st.radio("Type d'inventaire", ["🌍 Global (Tous les produits)", "🏢 Par Fournisseur"], horizontal=True)
    with col_inv2:
        date_inventaire = st.date_input("Date de l'inventaire", value=datetime.today(), key="date_inv")

    fournisseur_choisi = None
    if type_inventaire == "🏢 Par Fournisseur":
        if fours_avec_catalogue:
            with col_inv3:
                fournisseur_choisi = st.selectbox("Sélectionner le fournisseur", fours_avec_catalogue, key="sel_inv_four")
        else:
            st.warning("⚠️ Aucun fournisseur disponible.")

    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
        if type_inventaire == "🌍 Global (Tous les produits)":
            df_catalogue_inv = pd.read_sql_query(
                "SELECT nom, categorie, contenance, fournisseur, prix_unitaire FROM produits",
                conn
            )
        else:
            if fournisseur_choisi:
                df_catalogue_inv = pd.read_sql_query(
                    "SELECT nom, categorie, contenance, fournisseur, prix_unitaire FROM produits WHERE fournisseur = ?",
                    conn,
                    params=(fournisseur_choisi,)
                )
            else:
                df_catalogue_inv = pd.DataFrame()

    if df_catalogue_inv.empty:
        st.info("ℹ️ Aucun produit trouvé dans la base de données. Importe des catalogues ou saisis des factures pour alimenter le stock.")
    else:
        titre_section = "🌍 Inventaire Global de l'Établissement" if type_inventaire == "🌍 Global (Tous les produits)" else f"📋 Inventaire Fournisseur : {fournisseur_choisi}"
        st.subheader(titre_section)

        col_exp1, col_exp2 = st.columns([3, 1])
        with col_exp2:
            csv_export = df_catalogue_inv.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Exporter la feuille (CSV)",
                data=csv_export,
                file_name=f"feuille_inventaire_{datetime.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                help="Télécharge la liste pour l'imprimer ou l'ouvrir sur Excel."
            )

        st.info("💡 Renseigne la colonne **Quantité Constatée** pour chaque produit. Le montant total du stock s'actualisera instantanément.")

        df_edition = df_catalogue_inv.copy()
        df_edition["Quantité Constatée"] = 0.0
        
        if type_inventaire == "🌍 Global (Tous les produits)":
            df_edition = df_edition[["nom", "fournisseur", "categorie", "contenance", "prix_unitaire", "Quantité Constatée"]]
            df_edition.columns = ["Produit", "Fournisseur", "Catégorie", "Contenance", "Prix Unitaire (€)", "Quantité Constatée"]
            disabled_cols = ["Produit", "Fournisseur", "Catégorie", "Contenance", "Prix Unitaire (€)"]
        else:
            df_edition = df_edition[["nom", "categorie", "contenance", "prix_unitaire", "Quantité Constatée"]]
            df_edition.columns = ["Produit", "Catégorie", "Contenance", "Prix Unitaire (€)", "Quantité Constatée"]
            disabled_cols = ["Produit", "Catégorie", "Contenance", "Prix Unitaire (€)"]

        edited_inventaire = st.data_editor(
            df_edition,
            num_rows="fixed",
            use_container_width=True,
            key="editor_inventaire",
            disabled=disabled_cols
        )

        try:
            edited_inventaire["Montant Total (€)"] = edited_inventaire["Quantité Constatée"] * edited_inventaire["Prix Unitaire (€)"]
            valeur_totale_stock = edited_inventaire["Montant Total (€)"].sum()
        except Exception:
            valeur_totale_stock = 0.0

        st.divider()

        libelle_metrique = "💶 Valeur Totale du Stock Global" if type_inventaire == "🌍 Global (Tous les produits)" else f"💶 Valeur Totale de l'Inventaire ({fournisseur_choisi})"
        st.metric(label=libelle_metrique, value=f"{valeur_totale_stock:.2f} €")

        with st.expander("👁️ Voir le détail chiffré par ligne de produit"):
            st.dataframe(edited_inventaire, use_container_width=True)

        nom_archive_cible = "GLOBAL" if type_inventaire == "🌍 Global (Tous les produits)" else fournisseur_choisi

        if st.button("💾 Valider et Archiver cet Inventaire", type="primary"):
            try:
                details_json = edited_inventaire.to_json(orient="records")
                
                with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO inventaires_archives (date_inventaire, mode, valeur_totale, details_json) VALUES (?, ?, ?, ?)",
                        (str(date_inventaire), nom_archive_cible, float(valeur_totale_stock), details_json)
                    )
                    conn.commit()
                
                st.success(f"🎉 Inventaire archivé avec succès ! Valeur totale du stock : **{valeur_totale_stock:.2f} €**.")
            except Exception as e:
                st.error(f"❌ Erreur lors de l'enregistrement de l'inventaire : {e}")

# --- 5. PASSER UNE COMMANDE ---
elif choix == "Passer une commande":
    st.header("🛒 Passer une Commande")
    
    f_cmd = st.session_state.get("sidebar_f_cmd", "")
    btn_valider_cmd = st.session_state.get("sidebar_btn_cmd", False)

    if f_cmd:
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_cat = pd.read_sql_query("SELECT DISTINCT nom, contenance, prix_unitaire FROM produits WHERE fournisseur = ?", conn, params=(f_cmd,))
        
        if not df_cat.empty:
            st.markdown(f"### Catalogue de : **{f_cmd}**")
            st.info("💡 Renseigne les quantités de colis ou d'unités souhaitées, puis clique sur **Valider la commande** dans la barre latérale à gauche.")

            lignes_c = []
            for idx, r in df_cat.iterrows():
                c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 2])
                c1.text(r["nom"])
                c2.text(r["contenance"])
                c3.text(f"{r['prix_unitaire']} €")
                q_c = c4.number_input("Colis", min_value=0, step=1, key=f"col_{idx}")
                q_u = c5.number_input("Unité", min_value=0, step=1, key=f"uni_{idx}")
                if q_c > 0: lignes_c.append({"Produit": r["nom"], "Contenance": r["contenance"], "Type": "Colis", "Quantité": float(q_c)})
                if q_u > 0: lignes_c.append({"Produit": r["nom"], "Contenance": r["contenance"], "Type": "Unité", "Quantité": float(q_u)})
            
            if btn_valider_cmd:
                if lignes_c:
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        cur = conn.cursor()
                        for item in lignes_c:
                            cur.execute("INSERT INTO commandes (date_commande, fournisseur, produit, contenance, type_commande, quantite_commandee) VALUES (?, ?, ?, ?, ?, ?)",
                                        (str(datetime.today().date()), f_cmd, item["Produit"], item["Contenance"], item["Type"], item["Quantité"]))
                        conn.commit()
                    st.success("🎉 Commande enregistrée avec succès !")
                else:
                    st.warning("⚠️ Veuillez renseigner au moins une quantité (colis ou unité).")
        else:
            st.info("ℹ️ Aucun produit enregistré pour ce fournisseur.")
    else:
        st.warning("⚠️ Aucun fournisseur disponible.")

# --- 6. RÉCEPTION ---
elif choix == "Réception & Contrôle":
    st.header("✅ Réception & Contrôle")
    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
        df_c = pd.read_sql_query("SELECT DISTINCT fournisseur FROM commandes", conn)
    fours_c = df_c["fournisseur"].tolist() if not df_c.empty else []
    if fours_c:
        f_rec = st.selectbox("Fournisseur", fours_c)
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_cmd = pd.read_sql_query("SELECT * FROM commandes WHERE fournisseur = ?", conn, params=(f_rec,))
        if not df_cmd.empty:
            rec_data = []
            for _, r in df_cmd.iterrows():
                c1, c2, c3 = st.columns([3, 2, 2])
                c1.text(f"{r['produit']} ({r['type_commande']})")
                c2.text(f"Cmd : {r['quantite_commandee']}")
                q_rec = c3.number_input("Reçu", min_value=0, value=int(r['quantite_commandee']), step=1, key=f"rec_{r['id']}")
                ecart = float(r['quantite_commandee']) - float(q_rec)
                rec_data.append({"produit": r['produit'], "type": r['type_commande'], "cmd": float(r['quantite_commandee']), "recu": float(q_rec), "ecart": ecart})
            
            if st.button("Valider la réception"):
                with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                    cur = conn.cursor()
                    for item in rec_data:
                        statut = "Conforme" if item["ecart"] == 0 else "Écart"
                        cur.execute("INSERT INTO receptions (date_reception, fournisseur, produit, quantite_recue, statut) VALUES (?, ?, ?, ?, ?)",
                                    (str(datetime.today().date()), f_rec, item["produit"], item["recu"], statut))
                        if item["ecart"] > 0:
                            cur.execute("INSERT INTO reclamations (date_reception, fournisseur, produit, type_commande, quantite_commandee, quantite_recue, ecart, statut) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        (str(datetime.today().date()), f_rec, item["produit"], item["type"], item["cmd"], item["recu"], item["ecart"], "En attente de régulation"))
                    cur.execute("DELETE FROM commandes WHERE fournisseur = ?", (f_rec,))
                    conn.commit()
                st.success("Réception validée !")
                st.rerun()
        else:
            st.info("Aucune commande en cours pour ce fournisseur.")
    else:
        st.warning("Aucune commande enregistrée.")

# --- 7. RÉCLAMATIONS & ÉCARTS ---
elif choix == "Réclamations & Écarts":
    st.header("⚠️ Réclamations & Écarts")

    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
        df_rec = pd.read_sql_query("SELECT * FROM reclamations", conn)

    if not df_rec.empty:
        st.subheader("📋 Liste des litiges et écarts")
        st.dataframe(df_rec, use_container_width=True)

        st.divider()
        st.subheader("🛠️ Gestion de la régularisation")

        df_en_attente = df_rec[df_rec["statut"] == "En attente de régulation"]

        col_reg1, col_reg2 = st.columns(2)

        with col_reg1:
            st.markdown("#### 1️⃣ Régulariser article par article")
            if not df_en_attente.empty:
                options_litiges = {f"ID {r['id']} — {r['fournisseur']} : {r['produit']} (Écart: {r['ecart']})": r['id'] for _, r in df_en_attente.iterrows()}
                choix_litige_cle = st.selectbox("Sélectionner l'article à régulariser", list(options_litiges.keys()))
                
                if st.button("✅ Marquer cet article comme régularisé"):
                    litige_id = options_litiges[choix_litige_cle]
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("UPDATE reclamations SET statut = 'Régularisé' WHERE id = ?", (litige_id,))
                        conn.commit()
                    st.success("Article marqué comme régularisé !")
                    st.rerun()
            else:
                st.info("Aucun article en attente de régulation.")

        with col_reg2:
            st.markdown("#### 2️⃣ Régulariser toute la commande / tous les litiges")
            if not df_en_attente.empty:
                st.write("Si l'ensemble des litiges en cours a été résolu avec les fournisseurs :")
                if st.button("🚀 Tout marquer comme régularisé", type="primary"):
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute("UPDATE reclamations SET statut = 'Régularisé' WHERE statut = 'En attente de régulation'")
                        conn.commit()
                    st.success("Tous les écarts et réclamations ont été clôturés et régularisés !")
                    st.rerun()
            else:
                st.info("Tout est déjà régularisé !")
    else:
        st.info("Aucune réclamation ou écart enregistré pour le moment.")

# --- 8. HISTORIQUE & DOSSIERS FACTURES ---
elif choix == "Archives & Historique":
    st.header("📂 Historique, Factures & Inventaires Archivés")

    tab_h1, tab_h2, tab_h3 = st.tabs(["📋 Commandes & Réceptions", "📁 Dossiers de Factures", "📊 Historique des Inventaires"])

    with tab_h1:
        st.subheader("📦 Commandes & Réceptions")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_cmd_h = pd.read_sql_query("SELECT * FROM commandes", conn)
            df_rec_h = pd.read_sql_query("SELECT * FROM receptions", conn)
        st.write("**Commandes en cours :**")
        if not df_cmd_h.empty:
            st.dataframe(df_cmd_h, use_container_width=True)
        else:
            st.info("Aucune commande en cours.")
            
        st.write("**Réceptions validées :**")
        if not df_rec_h.empty:
            st.dataframe(df_rec_h, use_container_width=True)
        else:
            st.info("Aucune réception validée.")

    with tab_h2:
        st.subheader("📁 Dossiers de Factures par Fournisseur")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_fact_h = pd.read_sql_query("SELECT id, date_facture, fournisseur, montant_total, fichier_path FROM factures ORDER BY date_facture DESC", conn)
        
        if df_fact_h.empty:
            st.info("Aucune facture archivée.")
        else:
            for _, row in df_fact_h.iterrows():
                f_id = row["id"]
                f_date = row["date_facture"]
                f_four = row["fournisseur"]
                f_montant = row["montant_total"]
                f_path = row["fichier_path"]
                
                with st.expander(f"📄 Facture #{f_id} — {f_four} ({f_date}) — Total : {f_montant:.2f} €"):
                    col_info1, col_info2 = st.columns(2)
                    with col_info1:
                        st.write(f"**Fournisseur :** {f_four}")
                        st.write(f"**Date :** {f_date}")
                        st.write(f"**Montant :** {f_montant:.2f} €")
                    
                    with col_info2:
                        if f_path and os.path.exists(f_path):
                            st.write("**Document original :**")
                            with open(f_path, "rb") as file_to_dl:
                                file_bytes = file_to_dl.read()
                                file_ext = os.path.splitext(f_path)[1].lower()
                                mime = "application/pdf" if file_ext == ".pdf" else "image/jpeg"
                                st.download_button(
                                    label="📥 Télécharger / Ouvrir le fichier original",
                                    data=file_bytes,
                                    file_name=os.path.basename(f_path),
                                    mime=mime,
                                    key=f"dl_fact_{f_id}"
                                )
                        else:
                            st.info("Aucun fichier physique joint à cette facture.")
                    
                    st.divider()
                    st.write("**Détail des lignes de la facture :**")
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
                        df_lignes_fact = pd.read_sql_query("SELECT produit, categorie, contenance, quantite, prix_unitaire, total_ligne FROM lignes_facture WHERE facture_id = ?", conn, params=(f_id,))
                    if not df_lignes_fact.empty:
                        st.dataframe(df_lignes_fact, use_container_width=True)
                    else:
                        st.info("Aucun détail de ligne pour cette facture.")

    with tab_h3:
        st.subheader("📊 Historique des Inventaires Réalisés")
        with sqlite3.connect("inventaire_stock.db", timeout=60.0) as conn:
            df_inv_archives = pd.read_sql_query("SELECT id, date_inventaire, mode, valeur_totale FROM inventaires_archives ORDER BY date_inventaire DESC", conn)
        
        if df_inv_archives.empty:
            st.info("ℹ️ Aucun inventaire archivé pour le moment.")
        else:
            st.dataframe(df_inv_archives, use_container_width=True)
            
            st.divider()
            st.subheader("🔍 Consulter le détail d'un inventaire passé")
            
            options_inv = {f"Inventaire du {r['date_inventaire']} — Mode: {r['mode']} — Total: {r['valeur_totale']:.2f} €": r['id'] for _, r in df_inv_archives.iterrows()}
            
            if options_inv:
                choix_inv_cle = st.selectbox("Sélectionner l'inventaire à afficher", list(options_inv.keys()))
                
                if choix_inv_cle:
                    inv_id_sel = options_inv[choix_inv_cle]
                    with sqlite3.connect("inventaire_stock.db", timeout=60.0) as multiconn:
                        res_json = pd.read_sql_query("SELECT details_json FROM inventaires_archives WHERE id = ?", multiconn, params=(inv_id_sel,))
                    
                    if not res_json.empty:
                        json_str = res_json.iloc[0]["details_json"]
                        df_detail_inv = pd.read_json(io.StringIO(json_str))
                        st.dataframe(df_detail_inv, use_container_width=True)
            else:
                st.info("Aucun inventaire à consulter.")
