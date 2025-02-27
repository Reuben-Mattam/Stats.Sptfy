import ast
import eel
import pandas as pd
import io
import base64
import traceback
import os
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
web_dir = os.path.join(current_dir, 'web')
os.makedirs(web_dir, exist_ok=True)
eel.init(web_dir)



def analyze_top_music(processed_sheets):
    """
    Analyze top tracks, artists, albums, and genres across different time periods
    """
    
    # Updated sheet definitions with Artist in tracks/albums
    sheets = {
        "timestamp": ["Timestamp", "Track ID", "Album ID", "Artist ID", "Genres"],
        "tracks": ["Song Name", "Track ID", "Song URL", "Track Image", "Artist"],  # Added Artist
        "albums": ["Album", "Album ID", "Album Image", "Artist"],  # Added Artist
        "artists": ["Artist", "Artist ID", "Artist Image"],
        "genres": ["Genre", "Count"]
    }
    
    # Extract DataFrames
    df_timestamps = processed_sheets.get('timestamp')
    df_tracks = processed_sheets.get('tracks')
    df_artists = processed_sheets.get('artists')
    df_albums = processed_sheets.get('albums')
    df_genres = processed_sheets.get('genres')
    
    # Validate input
    if any(df is None for df in [df_timestamps, df_tracks, df_artists, df_albums, df_genres]):
        raise ValueError("Missing required sheets")
    
    # Ensure timestamp column is datetime
    df_timestamps['Timestamp'] = pd.to_datetime(df_timestamps['Timestamp'])
    
    # **Convert Genres column from string to list**
    df_timestamps['Genres'] = df_timestamps['Genres'].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )
    
    # Get current time
    now = datetime.now()
    
    # Define time periods
    time_periods = {
        'week': now - timedelta(days=7),
        'month': now - timedelta(days=30),
        'year': now - timedelta(days=365),
        'alltime': df_timestamps['Timestamp'].min()
    }
    
    # Initialize result dictionary
    top_music = {}
    
    # Music entity types to analyze
    entity_types = [
        ('tracks', 'Track ID', 'Song Name'), 
        ('artists', 'Artist ID', 'Artist'), 
        ('albums', 'Album ID', 'Album')
    ]
    
    for entity_type, id_column, name_column in entity_types:
        for period_name, period_start in time_periods.items():
            # Filter timestamps within the time period
            period_listens = df_timestamps[
                df_timestamps['Timestamp'] >= period_start
            ]
            
            # Group and count listens
            top_entities = period_listens.groupby(id_column).size().reset_index()
            
            # Rename columns
            top_entities.columns = ['id', 'count']
            
            # Sort by count (descending) and then by ID (ascending) for tie-breaking
            top_entities_sorted = top_entities.sort_values(
                ['count', 'id'], 
                ascending=[False, True]
            )
            
            # Get top 10 (or all if less than 10)
            top_10_ids = top_entities_sorted['id'].head(10).tolist()
            
            # Enrich with additional details (updated to include Artist where relevant)
            if entity_type == 'tracks':
                top_10_details = df_tracks[df_tracks['Track ID'].isin(top_10_ids)][
                    ['Track ID', 'Song Name', 'Artist', 'Song URL', 'Track Image']
                ].to_dict('records')
            elif entity_type == 'artists':
                top_10_details = df_artists[df_artists['Artist ID'].isin(top_10_ids)][
                    ['Artist ID', 'Artist', 'Artist Image']
                ].to_dict('records')
            else:  # albums
                top_10_details = df_albums[df_albums['Album ID'].isin(top_10_ids)][
                    ['Album ID', 'Album', 'Artist', 'Album Image']
                ].to_dict('records')
            
            # Store in result dictionary
            key_name = f'{period_name}_{entity_type}'
            top_music[key_name] = {
                'ids': top_10_ids,
                'details': top_10_details
            }
    
    # **Updated Genre Analysis**
    for period_name, period_start in time_periods.items():
        # Filter timestamps within the time period
        period_listens = df_timestamps[df_timestamps['Timestamp'] >= period_start]
        
        # Explode genres from the period's listens
        period_genres = period_listens['Genres'].explode()
        
        # Count genre frequencies
        genre_counts = period_genres.value_counts()
        
        # Get top 10 genres
        top_10_genres = genre_counts.head(10)
        
        # Store in result dictionary
        top_music[f'{period_name}_genres'] = {
            'ids': top_10_genres.index.tolist(),
            'details': [{'Genre': genre} for genre in top_10_genres.index.tolist()]
        }
    
    return top_music, df_timestamps, df_tracks, df_artists, df_albums, df_genres

@eel.expose
def process_file(filename, file_data):
    try:
        logger.info(f"Processing file: {filename}")
        
        content = base64.b64decode(file_data.split(',')[1])
        excel_sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        
        processed_sheets = {}
        
        # Define expected sheet names
        expected_sheets = ['timestamp', 'tracks', 'albums', 'artists', 'genres']
        
        # Validate and process sheets
        for expected_sheet in expected_sheets:
            # Find the sheet that matches the expected sheet name (case-insensitive)
            matching_sheets = [name for name in excel_sheets.keys() if name.lower() == expected_sheet]
            
            if not matching_sheets:
                raise ValueError(f"Missing required sheet: {expected_sheet}")
            
            # Use the first matching sheet
            sheet_name = matching_sheets[0]
            df = excel_sheets[sheet_name]
            
            # Updated column mappings with Artist in tracks/albums
            sheets_columns = {
                'timestamp': ["Timestamp", "Track ID", "Album ID", "Artist ID"],
                'tracks': ["Song Name", "Track ID", "Song URL", "Track Image", "Artist"],  # Added Artist
                'albums': ["Album", "Album ID", "Album Image", "Artist"],  # Added Artist
                'artists': ["Artist", "Artist ID", "Artist Image"],
                'genres': ['Genre', 'Count']
            }
            
            # Create a column mapping
            column_mapping = dict(zip(df.columns, sheets_columns[expected_sheet]))
            df = df.rename(columns=column_mapping)
            
            processed_sheets[expected_sheet] = df
        
        # Analyze top music
        top_music, df_timestamps, df_tracks, df_artists, df_albums, df_genres = analyze_top_music(processed_sheets)
        df_tracks.set_index('Track ID', inplace=True)
        df_artists.set_index('Artist ID', inplace=True)
        df_albums.set_index('Album ID', inplace=True)

        logger.info("File processed successfully!")
        
        return {
            "success": True, 
            "message": "File processed successfully!", 
            "sheets": list(processed_sheets.keys()),
            "data": processed_sheets,
            "top_music": top_music
        }
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return {"success": False, "message": str(e)}

# Log when the script starts
logger.info("Script is ready. Launching Eel...")

eel.start('index.html', size=(800, 600), mode='chrome', port=8000, host='localhost')



