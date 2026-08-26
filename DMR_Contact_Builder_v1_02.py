import os
import sys
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
VALID_RADIO_CHOICES = {
    "Baofeng DM-32UV",
    "AnyTone / BTech / Alinco DJ-MD5",
    "TYT / Retevis / Radioddity / OpenGD77"
}

VALID_SCOPE_CHOICES = {"US Only", "Global"}

def generate_csv_file(target_folder, update_status, update_progress, radio_choice, scope_choice="US Only"):
    if radio_choice not in VALID_RADIO_CHOICES:
        update_status("Error: Please select a radio model before generating.")
        return False, 0, None
    if scope_choice not in VALID_SCOPE_CHOICES:
        scope_choice = "US Only"

    update_progress(0)
    output_dir = target_folder
    
    scoped_export_path = os.path.join(output_dir, "RADIOID_EXPORT.csv") 
    intermediate_output_path = os.path.join(output_dir, "RADIOID_FCC_MERGED.csv") 
    fcc_zip_path = os.path.join(output_dir, "l_amat.zip")
    
    # Set final filename based on selection
    scope_suffix = "_GLOBAL" if scope_choice == "Global" else ""
    if radio_choice == "Baofeng DM-32UV":
        final_filename = f"DMR_CONTACTS_BAOFENG{scope_suffix}.csv"
    elif radio_choice == "AnyTone / BTech / Alinco DJ-MD5":
        final_filename = f"DMR_CONTACTS_ANYTONE_FAMILY{scope_suffix}.csv"
    else:
        final_filename = f"DMR_CONTACTS_TYT_RADIODDITY{scope_suffix}.csv"
        
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
        return False, 0, None

    update_progress(8)
    df_radio.columns = [c.lower() for c in df_radio.columns]

    if scope_choice == "Global":
        update_status("Using global RadioID data (all countries)...")
        df_scoped = df_radio.copy()
    else:
        update_status("Filtering RadioID data for 'United States'...")
        df_scoped = df_radio[df_radio['country'] == 'United States'].copy()
    df_scoped.reset_index(drop=True, inplace=True)
    
    rename_map = {
        'radio_id': 'RADIO_ID',
        'callsign': 'CALLSIGN',
        'fname': 'FIRST_NAME',
        'city': 'CITY',
        'state': 'STATE',
        'country': 'COUNTRY'
    }
    df_scoped.rename(columns=rename_map, inplace=True)

    cols_to_keep = ['RADIO_ID', 'CALLSIGN', 'FIRST_NAME', 'CITY', 'STATE', 'COUNTRY']
    for col in cols_to_keep:
        if col not in df_scoped.columns:
            df_scoped[col] = ""
            
    df_scoped = df_scoped[cols_to_keep]
    df_scoped['CALLSIGN'] = df_scoped['CALLSIGN'].astype(str).str.strip().str.upper()

    try:
        df_scoped.to_csv(scoped_export_path, index=False)
    except IOError as e:
        update_status(f"Error saving intermediate file: {e}")
        return False, 0, None

    update_progress(12)

    # --- Download FCC Data ---
    update_status("Downloading FCC database (l_amat.zip)... This takes a moment.")
    fcc_url = "https://data.fcc.gov/download/pub/uls/complete/l_amat.zip"
    max_retries = 3
    download_successful = False
    
    for attempt in range(1, max_retries + 1):
        try:
            with requests.get(fcc_url, stream=True, headers=browser_headers, timeout=(30, 300)) as r:
                r.raise_for_status()
                total_bytes = int(r.headers.get('content-length', 0))
                downloaded_bytes = 0
                last_reported_pct = -1
                with open(fcc_zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if total_bytes:
                                pct = int(downloaded_bytes * 100 / total_bytes)
                                if pct != last_reported_pct:
                                    last_reported_pct = pct
                                    update_status(f"Downloading FCC database... {pct}%")
                                    update_progress(12 + (pct * 0.48))
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
                return False, 0, None

    if not download_successful:
        return False, 0, None

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
        return False, 0, None

    if os.path.exists(fcc_zip_path):
        os.remove(fcc_zip_path)

    update_progress(65)
    update_status("Cleaning FCC data...")
    df_fcc.fillna("", inplace=True)
    df_fcc['CALLSIGN'] = df_fcc['CALLSIGN'].astype(str).str.strip().str.upper()

    formatted_fcc_names = []
    total_fcc_rows = len(df_fcc)
    report_every = max(total_fcc_rows // 25, 1)
    for i, row in enumerate(df_fcc.itertuples(index=False)):
        if row.ENTITY_NAME.strip():
            formatted_fcc_names.append(row.ENTITY_NAME.strip())
        else:
            parts = [row.FCC_FIRST, row.FCC_MI, row.FCC_LAST]
            full_name = " ".join([p.strip() for p in parts if p.strip()])
            formatted_fcc_names.append(full_name)
        if i % report_every == 0:
            update_progress(65 + (i / total_fcc_rows) * 10)
            
    df_fcc['FCC_FULL_NAME'] = formatted_fcc_names
    df_fcc.drop_duplicates(subset=['CALLSIGN'], keep='last', inplace=True)

    # --- Merge Data ---
    update_status("Merging RadioID contacts with FCC records...")
    df_merged = pd.merge(df_scoped, df_fcc, on='CALLSIGN', how='left')

    def _prefer_fcc(fcc_col, fallback_col):
        fcc_series = df_merged[fcc_col].astype(str).replace('nan', '')
        has_fcc_value = df_merged[fcc_col].notna() & (fcc_series.str.strip() != "")
        return fcc_series.where(has_fcc_value, df_merged[fallback_col])

    df_merged['FIRST_NAME'] = _prefer_fcc('FCC_FULL_NAME', 'FIRST_NAME')
    df_merged['CITY'] = _prefer_fcc('FCC_CITY', 'CITY')
    df_merged['STATE'] = _prefer_fcc('FCC_STATE', 'STATE')

    update_progress(78)

    cols_to_drop = ['ENTITY_NAME', 'FCC_FIRST', 'FCC_MI', 'FCC_LAST', 'FCC_CITY', 'FCC_STATE', 'FCC_FULL_NAME']
    df_merged.drop(columns=cols_to_drop, inplace=True, errors='ignore')

    try:
        df_merged.to_csv(intermediate_output_path, index=False)
    except IOError as e:
        update_status(f"Error saving merged output file: {e}")

    update_progress(82)

    # --- Formatting Data ---
    update_status(f"Formatting data for {radio_choice} import structure...")
    formatted_records = []

    state_mapping = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
        'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
        'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
        'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
        'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
        'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
        'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
        'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
        'DC': 'District of Columbia', 'PR': 'Puerto Rico', 'GU': 'Guam',
        'VI': 'U.S. Virgin Islands', 'AS': 'American Samoa', 'MP': 'Northern Mariana Islands'
    }

    banned_suffixes = {'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'md', 'phd', 'dds', 'esq'}

    total_merged_rows = len(df_merged)
    format_report_every = max(total_merged_rows // 25, 1)
    for index, row in enumerate(df_merged.itertuples(index=False)):
        if index % format_report_every == 0:
            update_progress(82 + (index / total_merged_rows) * 14)
        raw_name = str(row.FIRST_NAME).strip()
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

        raw_city_line = str(row.CITY).strip()
        clean_city = raw_city_line
        clean_state = str(row.STATE).strip() 

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

        raw_country = str(row.COUNTRY).strip()
        clean_country = "USA" if raw_country.upper() == "UNITED STATES" else raw_country.title()

        # Format depending on radio selection
        if radio_choice == "Baofeng DM-32UV":
            formatted_records.append({
                'No.': index + 1,
                'RADIO_ID': row.RADIO_ID,
                'Repeater': row.CALLSIGN,
                'Name': clean_name,
                'City': clean_city,
                'Province': clean_state,
                'Country': clean_country,
                'Remark': '',
                'Type': 'Private Call',
                'Alert Call': '0'
            })
        elif radio_choice == "AnyTone / BTech / Alinco DJ-MD5":
            formatted_records.append({
                'No.': index + 1,
                'Radio ID': row.RADIO_ID,
                'Callsign': row.CALLSIGN,
                'Name': clean_name,
                'City': clean_city,
                'State': clean_state,
                'Country': clean_country,
                'Remarks': '',
                'Call Type': 'Private Call',
                'Call Alert': 'None'
            })
        else: # TYT, Retevis, Radioddity, OpenGD77 format
            formatted_records.append({
                'Radio ID': row.RADIO_ID,
                'CallSign': row.CALLSIGN,
                'Name': clean_name,
                'City': clean_city,
                'State': clean_state,
                'Country': clean_country
            })

    df_formatted = pd.DataFrame(formatted_records)
    try:
        df_formatted.to_csv(final_import_path, index=False)
        update_status("Cleaning up intermediate files...")
        
        if os.path.exists(scoped_export_path):
            os.remove(scoped_export_path)
        if os.path.exists(intermediate_output_path):
            os.remove(intermediate_output_path)

        update_progress(100)
        return True, len(df_formatted), final_import_path
    except IOError as e:
        update_status(f"Error saving final formatted output file: {e}")
        return False, 0, None

# ==========================================
# PART 2: THE GUI SETUP
# ==========================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# --- Ham radio panel palette ---
COLOR_BG = "#1C1E1B"                    # outer panel background
COLOR_PANEL_BORDER = "#3A3D37"
COLOR_FIELD_BG = "#15160F"              # inner field background
COLOR_FIELD_CONTROL = "#232520"         # buttons/controls sitting on fields
COLOR_FIELD_CONTROL_HOVER = "#2C2E28"
COLOR_ACCENT = "#639922"                # moss green
COLOR_ACCENT_HOVER = "#527D1C"
COLOR_ACCENT_TEXT_ON_LIGHT = "#173404"  # dark text for use on green fills
COLOR_TEXT_BRIGHT = "#EAF3DE"
COLOR_TEXT_MUTED = "#5F5E5A"
COLOR_ERROR = "#E24B4A"
FONT_MONO = "Consolas"

app = ctk.CTk()
app.title("DMR Contact Builder v1.02")
app.geometry("650x460")

def resource_path(filename):
    # When frozen by PyInstaller (--onefile), bundled files are extracted to a
    # temp folder pointed to by sys._MEIPASS. Otherwise, look next to this script.
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, filename)

try:
    app.iconbitmap(resource_path("dmr_icon.ico"))
except Exception:
    pass  # Fall back to the default icon if the file is missing on this machine

output_folder = ""

def choose_folder():
    global output_folder
    selected = filedialog.askdirectory(title="Select Output Folder")
    if selected:
        output_folder = selected
        display_path = output_folder if len(output_folder) < 48 else "..." + output_folder[-45:]
        path_label.configure(text=display_path, text_color=COLOR_TEXT_BRIGHT)

def update_gui_status(message, color=COLOR_TEXT_MUTED):
    status_label.configure(text=message, text_color=color)

def update_gui_progress(pct):
    pct = max(0, min(100, pct))
    progress_bar.set(pct / 100)
    percent_label.configure(text=f"{int(pct)}%")

def run_script_thread(selected_radio, selected_scope):
    try:
        success, contact_count, output_path = generate_csv_file(
            output_folder, update_gui_status, update_gui_progress, selected_radio, selected_scope
        )
        if success:
            update_gui_status(
                f"COMPLETE — {contact_count:,} contacts saved to {os.path.basename(output_path)}",
                COLOR_ACCENT
            )
        else:
            update_gui_progress(0)
    except Exception as e:
        update_gui_status(f"FAILED: {str(e)}", COLOR_ERROR)
        update_gui_progress(0)
    finally:
        activate_button.configure(state="normal", text="▶ GENERATE")

def activate_script():
    if not output_folder:
        update_gui_status("ERROR: Select an output folder first", COLOR_ERROR)
        return

    selected_radio = radio_var.get()
    if selected_radio not in VALID_RADIO_CHOICES:
        update_gui_status("ERROR: Select a radio model first", COLOR_ERROR)
        return

    selected_scope = scope_var.get()
    if selected_scope not in VALID_SCOPE_CHOICES:
        update_gui_status("ERROR: Select a coverage option first", COLOR_ERROR)
        return

    activate_button.configure(state="disabled", text="DOWNLOADING...")
    if not progress_frame.winfo_ismapped():
        app.geometry("650x510")
        progress_frame.pack(fill="x", padx=30, pady=(0, 4), before=status_label)
    update_gui_progress(0)
    thread = threading.Thread(target=run_script_thread, args=(selected_radio, selected_scope))
    thread.start()

# --- UI Layout ---
main_frame = ctk.CTkFrame(app, fg_color=COLOR_BG, corner_radius=0)
main_frame.pack(fill="both", expand=True)

# Header row: title (left), byline (right)
header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
header_frame.pack(fill="x", padx=30, pady=(22, 14))

title = ctk.CTkLabel(
    header_frame, text="📡 DMR CONTACT BUILDER",
    font=(FONT_MONO, 18, "bold"), text_color=COLOR_TEXT_BRIGHT
)
title.pack(side="left")

byline = ctk.CTkLabel(
    header_frame, text="by KR4DSO",
    font=(FONT_MONO, 12), text_color=COLOR_ACCENT
)
byline.pack(side="right")

divider = ctk.CTkFrame(main_frame, fg_color=COLOR_PANEL_BORDER, height=1)
divider.pack(fill="x", padx=30, pady=(0, 16))

# Radio Format field
radio_field = ctk.CTkFrame(main_frame, fg_color=COLOR_FIELD_BG, corner_radius=8)
radio_field.pack(fill="x", padx=30, pady=(0, 10))

radio_label = ctk.CTkLabel(
    radio_field, text="RADIO FORMAT",
    font=(FONT_MONO, 11), text_color=COLOR_ACCENT
)
radio_label.pack(anchor="w", padx=14, pady=(10, 2))

radio_var = ctk.StringVar(value="choose your radio model")
radio_dropdown = ctk.CTkOptionMenu(
    radio_field,
    variable=radio_var,
    values=[
        "Baofeng DM-32UV",
        "AnyTone / BTech / Alinco DJ-MD5",
        "TYT / Retevis / Radioddity / OpenGD77"
    ],
    fg_color=COLOR_FIELD_BG,
    button_color=COLOR_FIELD_CONTROL,
    button_hover_color=COLOR_FIELD_CONTROL_HOVER,
    dropdown_fg_color=COLOR_FIELD_CONTROL,
    dropdown_hover_color=COLOR_ACCENT,
    dropdown_text_color=COLOR_TEXT_BRIGHT,
    text_color=COLOR_TEXT_BRIGHT,
    font=(FONT_MONO, 13),
    dropdown_font=(FONT_MONO, 13),
    corner_radius=6
)
radio_dropdown.pack(fill="x", padx=14, pady=(0, 12))

# Coverage field
scope_field = ctk.CTkFrame(main_frame, fg_color=COLOR_FIELD_BG, corner_radius=8)
scope_field.pack(fill="x", padx=30, pady=(0, 10))

scope_label = ctk.CTkLabel(
    scope_field, text="COVERAGE",
    font=(FONT_MONO, 11), text_color=COLOR_ACCENT
)
scope_label.pack(anchor="w", padx=14, pady=(10, 2))

scope_var = ctk.StringVar(value="US Only")
scope_toggle = ctk.CTkSegmentedButton(
    scope_field,
    variable=scope_var,
    values=["US Only", "Global"],
    fg_color=COLOR_BG,
    selected_color=COLOR_ACCENT,
    selected_hover_color=COLOR_ACCENT_HOVER,
    unselected_color=COLOR_FIELD_CONTROL,
    unselected_hover_color=COLOR_FIELD_CONTROL_HOVER,
    text_color=COLOR_TEXT_MUTED,
    text_color_disabled=COLOR_TEXT_MUTED,
    font=(FONT_MONO, 12, "bold"),
    corner_radius=6
)
scope_toggle.pack(fill="x", padx=14, pady=(0, 12))

# Output Folder field
folder_field = ctk.CTkFrame(main_frame, fg_color=COLOR_FIELD_BG, corner_radius=8)
folder_field.pack(fill="x", padx=30, pady=(0, 18))

folder_label = ctk.CTkLabel(
    folder_field, text="OUTPUT PATH",
    font=(FONT_MONO, 11), text_color=COLOR_ACCENT
)
folder_label.pack(anchor="w", padx=14, pady=(10, 4))

folder_row = ctk.CTkFrame(folder_field, fg_color="transparent")
folder_row.pack(fill="x", padx=14, pady=(0, 12))

browse_btn = ctk.CTkButton(
    folder_row, text="Browse", width=90, height=28,
    fg_color=COLOR_FIELD_CONTROL, hover_color=COLOR_ACCENT,
    text_color=COLOR_TEXT_BRIGHT, font=(FONT_MONO, 12),
    corner_radius=6, command=choose_folder
)
browse_btn.pack(side="left", padx=(0, 10))

path_label = ctk.CTkLabel(
    folder_row, text="/no folder selected/",
    font=(FONT_MONO, 12), text_color=COLOR_TEXT_MUTED
)
path_label.pack(side="left")

# Activate Button
activate_button = ctk.CTkButton(
    main_frame,
    text="▶ GENERATE",
    font=(FONT_MONO, 15, "bold"),
    height=44,
    fg_color=COLOR_ACCENT,
    hover_color=COLOR_ACCENT_HOVER,
    text_color=COLOR_ACCENT_TEXT_ON_LIGHT,
    corner_radius=6,
    command=activate_script
)
activate_button.pack(fill="x", padx=30, pady=(0, 14))

# Progress Bar (hidden until Generate is pressed)
progress_frame = ctk.CTkFrame(main_frame, fg_color="transparent")

progress_bar = ctk.CTkProgressBar(
    progress_frame, height=14,
    fg_color=COLOR_FIELD_BG, progress_color=COLOR_ACCENT,
    corner_radius=4
)
progress_bar.set(0)
progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))

percent_label = ctk.CTkLabel(
    progress_frame, text="0%",
    font=(FONT_MONO, 12, "bold"), text_color=COLOR_ACCENT, width=40
)
percent_label.pack(side="left")

# progress_frame is intentionally not packed here — it's revealed in activate_script()
# once the user actually presses Generate, so it's invisible until then.

status_label = ctk.CTkLabel(
    main_frame, text="",
    font=(FONT_MONO, 11), text_color=COLOR_TEXT_MUTED
)
status_label.pack(padx=30, pady=(4, 16), anchor="w")

if __name__ == "__main__":
    app.mainloop()