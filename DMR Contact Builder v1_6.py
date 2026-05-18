import os
import time
import requests
import zipfile
import io
import pandas as pd
import threading
import customtkinter as ctk
from tkinter import filedialog

# =========================================================
# PART 1: THE DATA LOGIC (RadioID_FCCULS_v1_00)
# ==========================================
def generate_csv_file(target_folder, update_status, radio_choice):
    output_dir = target_folder
    
    us_radioid_path = os.path.join(output_dir, "US_RADIOID.csv") 
    intermediate_output_path = os.path.join(output_dir, "RADIOID_FCC_MERGED.csv") 
    fcc_zip_path = os.path.join(output_dir, "l_amat.zip")
    
    # Set final filename based on selection
    if radio_choice == "Baofeng DM-32UV":
        final_filename = "DMR_CONTACTS_BAOFENG.csv"
    elif radio_choice in ["AnyTone AT-D578/868/878", "BTech DMR-6X2 / 6X2 Pro"]:
        final_filename = "DMR_CONTACTS_ANYTONE_BTECH.csv"
    else:
        final_filename = "DMR_CONTACTS_TYT_RETEVIS.csv"
        
    final_import_path = os.path.join(output_dir, final_filename)

    os.makedirs(output_dir, exist_ok=True)

    # --- Fetch RadioID Data ---
    update_status("Downloading daily database dump from RadioID.net...")
    cache_buster = str(time.time()).replace('.', '')
    radio_id_url = f"https://radioid.net/static/user.csv?v={cache_buster}"
    
    browser_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(radio_id_url, headers=browser_headers, timeout=30)
        response.raise_for_status() 
        df_radio = pd.read_csv(io.StringIO(response.text), low_memory=False)
    except Exception as e:
        update_status(f"Error downloading RadioID data: {e}")
        return False

    df_radio.columns = [c.lower() for c in df_radio.columns]

    update_status("Filtering RadioID data for 'United States'...")
    df_us = df_radio[df_radio['country'] == 'United States'].copy()
    df_us.reset_index(drop=True, inplace=True)
    
    rename_map = {
        'radio_id': 'RADIO_ID',
        'callsign': 'CALLSIGN',
        'fname': 'FIRST_NAME',
        'city': 'CITY',
        'state': 'STATE',
        'country': 'COUNTRY'
    }
    df_us.rename(columns=rename_map, inplace=True)

    cols_to_keep = ['RADIO_ID', 'CALLSIGN', 'FIRST_NAME', 'CITY', 'STATE', 'COUNTRY']
    for col in cols_to_keep:
        if col not in df_us.columns:
            df_us[col] = ""
            
    df_us = df_us[cols_to_keep]
    df_us['CALLSIGN'] = df_us['CALLSIGN'].astype(str).str.strip().str.upper()

    try:
        df_us.to_csv(us_radioid_path, index=False)
    except IOError as e:
        update_status(f"Error saving intermediate file: {e}")
        return False

    # --- Download FCC Data ---
    update_status("Downloading FCC database (l_amat.zip)... This takes a moment.")
    fcc_url = "https://data.fcc.gov/download/pub/uls/complete/l_amat.zip"
    max_retries = 3
    download_successful = False
    
    for attempt in range(1, max_retries + 1):
        try:
            with requests.get(fcc_url, stream=True, headers=browser_headers, timeout=(30, 300)) as r:
                r.raise_for_status()
                with open(fcc_zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        if chunk: 
                            f.write(chunk)
            download_successful = True
            break 
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                update_status(f"FCC Download failed. Retrying... ({attempt}/{max_retries})")
                time.sleep(5)
            else:
                update_status("CRITICAL: FCC servers are unresponsive.")
                if os.path.exists(fcc_zip_path):
                    os.remove(fcc_zip_path)
                return False

    if not download_successful:
        return False

    try:
        update_status("Extracting and parsing FCC database...")
        fcc_columns = [4, 7, 8, 9, 10, 16, 17]
        fcc_names = ['CALLSIGN', 'ENTITY_NAME', 'FCC_FIRST', 'FCC_MI', 'FCC_LAST', 'FCC_CITY', 'FCC_STATE']
        
        with zipfile.ZipFile(fcc_zip_path, 'r') as zip_ref:
            with zip_ref.open('EN.dat') as en_file:
                df_fcc = pd.read_csv(
                    en_file, 
                    sep='|', 
                    header=None, 
                    usecols=fcc_columns, 
                    names=fcc_names, 
                    encoding='latin-1', 
                    dtype=str,
                    on_bad_lines='skip'
                )
    except Exception as e:
        update_status(f"Error parsing downloaded FCC data: {e}")
        if os.path.exists(fcc_zip_path):
            os.remove(fcc_zip_path)
        return False

    if os.path.exists(fcc_zip_path):
        os.remove(fcc_zip_path)

    update_status("Cleaning FCC data...")
    df_fcc.fillna("", inplace=True)
    df_fcc['CALLSIGN'] = df_fcc['CALLSIGN'].astype(str).str.strip().str.upper()

    formatted_fcc_names = []
    for index, row in df_fcc.iterrows():
        if row['ENTITY_NAME'].strip():
            formatted_fcc_names.append(row['ENTITY_NAME'].strip())
        else:
            parts = [row['FCC_FIRST'], row['FCC_MI'], row['FCC_LAST']]
            full_name = " ".join([p.strip() for p in parts if p.strip()])
            formatted_fcc_names.append(full_name)
            
    df_fcc['FCC_FULL_NAME'] = formatted_fcc_names
    df_fcc.drop_duplicates(subset=['CALLSIGN'], keep='last', inplace=True)

    # --- Merge Data ---
    update_status("Merging RadioID contacts with FCC records...")
    df_merged = pd.merge(df_us, df_fcc, on='CALLSIGN', how='left')

    df_merged['FIRST_NAME'] = df_merged.apply(
        lambda row: row['FCC_FULL_NAME'] if pd.notna(row['FCC_FULL_NAME']) and str(row['FCC_FULL_NAME']).strip() != "" else row['FIRST_NAME'], 
        axis=1
    )
    df_merged['CITY'] = df_merged.apply(
        lambda row: row['FCC_CITY'] if pd.notna(row['FCC_CITY']) and str(row['FCC_CITY']).strip() != "" else row['CITY'], 
        axis=1
    )
    df_merged['STATE'] = df_merged.apply(
        lambda row: row['FCC_STATE'] if pd.notna(row['FCC_STATE']) and str(row['FCC_STATE']).strip() != "" else row['STATE'], 
        axis=1
    )

    cols_to_drop = ['ENTITY_NAME', 'FCC_FIRST', 'FCC_MI', 'FCC_LAST', 'FCC_CITY', 'FCC_STATE', 'FCC_FULL_NAME']
    df_merged.drop(columns=cols_to_drop, inplace=True, errors='ignore')

    try:
        df_merged.to_csv(intermediate_output_path, index=False)
    except IOError as e:
        update_status(f"Error saving merged output file: {e}")

    # --- Formatting Data ---
    update_status(f"Formatting data for {radio_choice} import structure...")
    formatted_records = []

    state_mapping = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
        'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 'Gu':'Guam',
        'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
        'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
        'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
        'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
        'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
        'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
        'DC': 'District of Columbia', 'PR': 'Puerto Rico'
    }

    banned_suffixes = {'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'md', 'phd', 'dds', 'esq'}

    for index, row in df_merged.iterrows():
        raw_name = str(row['FIRST_NAME']).strip()
        if ',' in raw_name:
            name_parts = raw_name.split(',', 1)
            clean_name = f"{name_parts[1].strip()} {name_parts[0].strip()}"
        else:
            clean_name = raw_name
            
        name_words = clean_name.split()
        while len(name_words) > 1:
            last_word_clean = name_words[-1].replace('.', '').lower()
            if last_word_clean in banned_suffixes:
                name_words.pop()
            else:
                break 
                
        clean_name = " ".join(name_words).title()

        raw_city_line = str(row['CITY']).strip()
        clean_city = raw_city_line
        clean_state = str(row['STATE']).strip() 

        if ',' in raw_city_line:
            city_parts = raw_city_line.split(',', 1)
            clean_city = city_parts[0].strip()
            state_zip = city_parts[1].strip()
            
            sz_parts = state_zip.rsplit(' ', 1)
            if len(sz_parts) == 2 and any(char.isdigit() for char in sz_parts[1]):
                clean_state = sz_parts[0].strip()
            else:
                clean_state = state_zip.strip()

        clean_city = clean_city.title()
        
        state_upper = clean_state.upper()
        if state_upper in state_mapping:
            clean_state = state_mapping[state_upper]
        else:
            clean_state = clean_state.title()

        raw_country = str(row['COUNTRY']).strip()
        clean_country = "USA" if raw_country.upper() == "UNITED STATES" else raw_country.title()

        # Format depending on radio selection
        if radio_choice == "Baofeng DM-32UV":
            formatted_records.append({
                'No.': index + 1,
                'RADIO_ID': row['RADIO_ID'],
                'Repeater': row['CALLSIGN'],
                'Name': clean_name,
                'City': clean_city,
                'Province': clean_state,
                'Country': clean_country,
                'Remark': '',
                'Type': 'Private Call',
                'Alert Call': '0'
            })
        elif radio_choice in ["AnyTone AT-D578/868/878", "BTech DMR-6X2 / 6X2 Pro"]:
            formatted_records.append({
                'No.': index + 1,
                'Radio ID': row['RADIO_ID'],
                'Callsign': row['CALLSIGN'],
                'Name': clean_name,
                'City': clean_city,
                'State': clean_state,
                'Country': clean_country,
                'Remarks': '',
                'Call Type': 'Private Call',
                'Call Alert': 'None'
            })
        else: # TYT & Retevis formats
            formatted_records.append({
                'Radio ID': row['RADIO_ID'],
                'CallSign': row['CALLSIGN'],
                'Name': clean_name,
                'City': clean_city,
                'State': clean_state,
                'Country': clean_country
            })

    df_formatted = pd.DataFrame(formatted_records)
    try:
        df_formatted.to_csv(final_import_path, index=False)
        update_status("Cleaning up intermediate files...")
        
        if os.path.exists(us_radioid_path):
            os.remove(us_radioid_path)
        if os.path.exists(intermediate_output_path):
            os.remove(intermediate_output_path)
            
        return True
    except IOError as e:
        update_status(f"Error saving final formatted output file: {e}")
        return False

# ==========================================
# PART 2: THE GUI SETUP
# ==========================================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("DMR Contact Builder")
app.geometry("650x420") 

output_folder = ""

def choose_folder():
    global output_folder
    selected = filedialog.askdirectory(title="Select Output Folder")
    if selected:
        output_folder = selected
        path_label.configure(text=f"Saving to: {output_folder}")

def update_gui_status(message, color="white"):
    status_label.configure(text=message, text_color=color)

def run_script_thread(selected_radio):
    try:
        success = generate_csv_file(output_folder, update_gui_status, selected_radio)
        if success:
            update_gui_status(f"Complete! CSV is ready for {selected_radio}.", "#00CC66")
    except Exception as e:
        update_gui_status(f"Failed: {str(e)}", "#FF4C4C")
    finally:
        activate_button.configure(state="normal", text="GENERATE")

def activate_script():
    if not output_folder:
        update_gui_status("Error: Please choose a folder first!", "#FF4C4C")
        return
    
    selected_radio = radio_var.get()
    activate_button.configure(state="disabled", text="DOWNLOADING...")
    thread = threading.Thread(target=run_script_thread, args=(selected_radio,))
    thread.start()

# --- UI Layout ---
title = ctk.CTkLabel(app, text="DMR Contact List Generator", font=("Segoe UI", 24, "bold"))
title.pack(pady=(20, 10))

# Target Radio Selection
radio_frame = ctk.CTkFrame(app, fg_color="transparent")
radio_frame.pack(pady=(0, 15))

radio_label = ctk.CTkLabel(radio_frame, text="Select Radio Format:", font=("Segoe UI", 14))
radio_label.pack(side="left", padx=(0, 10))

# Setup Dropdown Menu with New Options
radio_var = ctk.StringVar(value="Baofeng DM-32UV")
radio_dropdown = ctk.CTkOptionMenu(
    radio_frame, 
    variable=radio_var, 
    values=[
        "Baofeng DM-32UV", 
        "AnyTone AT-D578/868/878",
        "BTech DMR-6X2/DMR-6X2 Pro",
        "TYT & Retevis (MD-9600, MD-UV380, RT-3S, RT-90)"
    ],
    width=350 
)
radio_dropdown.pack(side="left")

# Output Folder Selection
instructions = ctk.CTkLabel(app, text="Select a destination to save your formatted CSV.", font=("Segoe UI", 14))
instructions.pack(pady=(0, 10))

folder_frame = ctk.CTkFrame(app, fg_color="transparent")
folder_frame.pack(fill="x", padx=40)

browse_btn = ctk.CTkButton(folder_frame, text="Browse...", width=100, command=choose_folder)
browse_btn.pack(side="left", padx=(0, 10))

path_label = ctk.CTkLabel(folder_frame, text="No folder selected", text_color="gray")
path_label.pack(side="left")

# Activate Button
activate_button = ctk.CTkButton(
    app, 
    text="GENERATE", 
    font=("Segoe UI", 16, "bold"), 
    height=45, 
    width=200,
    fg_color="#28a745",
    hover_color="#218838",
    command=activate_script
)
activate_button.pack(pady=25)

status_label = ctk.CTkLabel(app, text="", font=("Segoe UI", 14))
status_label.pack()

if __name__ == "__main__":
    app.mainloop()