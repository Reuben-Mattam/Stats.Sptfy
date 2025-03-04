import ast
import eel
import pandas as pd
import io
import base64
import traceback
import os
import logging
import json
import math
import numpy as np
from datetime import datetime, timedelta

# logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
web_dir = os.path.join(current_dir, 'web')
os.makedirs(web_dir, exist_ok=True)
eel.init(web_dir)



def analyze_top_music(processed_sheets):
    """
    analyse sheets and get dictionary of top tracks, albums, artist, genres
    """
    
    sheets = {
        "timestamp": ["Timestamp", "Track ID", "Album ID", "Artist ID", "Genres"],
        "tracks": ["Song Name", "Track ID", "Song URL", "Track Image", "Artist"],
        "albums": ["Album", "Album ID", "Album Image", "Artist"],
        "artists": ["Artist", "Artist ID", "Artist Image"],
        "genres": ["Genre", "Count"]
    }
    
    df_timestamps = processed_sheets.get('timestamp')
    df_tracks = processed_sheets.get('tracks')
    df_artists = processed_sheets.get('artists')
    df_albums = processed_sheets.get('albums')
    df_genres = processed_sheets.get('genres')
    
    if any(df is None for df in [df_timestamps, df_tracks, df_artists, df_albums, df_genres]):
        raise ValueError("Missing required sheets")
    
    df_timestamps['Timestamp'] = pd.to_datetime(df_timestamps['Timestamp'])
    df_timestamps['Genres'] = df_timestamps['Genres'].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )

    now = datetime.now()
    
    # time periods
    time_periods = {
        'week': now - timedelta(days=7),
        'month': now - timedelta(days=30),
        'year': now - timedelta(days=365),
        'alltime': df_timestamps['Timestamp'].min()
    }
    
    top_music = {}
    
    # entity types
    entity_types = [
        ('tracks', 'Track ID', 'Song Name'), 
        ('artists', 'Artist ID', 'Artist'), 
        ('albums', 'Album ID', 'Album')
    ]
    
    for entity_type, id_column, name_column in entity_types:
        for period_name, period_start in time_periods.items():

            period_listens = df_timestamps[
                df_timestamps['Timestamp'] >= period_start
            ]
            top_entities = period_listens.groupby(id_column).size().reset_index()
            top_entities.columns = ['id', 'count']
            
            # uses id for tiebreaks
            top_entities_sorted = top_entities.sort_values(
                ['count', 'id'], 
                ascending=[False, True]
            )
            
            top_10_ids = top_entities_sorted['id'].head(10).tolist()
            
            if entity_type == 'tracks':
                top_10_details = df_tracks[df_tracks['Track ID'].isin(top_10_ids)][
                    ['Track ID', 'Song Name', 'Artist', 'Song URL', 'Track Image']
                ].to_dict('records')
            elif entity_type == 'artists':
                top_10_details = df_artists[df_artists['Artist ID'].isin(top_10_ids)][
                    ['Artist ID', 'Artist', 'Artist Image']
                ].to_dict('records')
            else:
                top_10_details = df_albums[df_albums['Album ID'].isin(top_10_ids)][
                    ['Album ID', 'Album', 'Artist', 'Album Image']
                ].to_dict('records')
            
            key_name = f'{period_name}_{entity_type}'
            top_music[key_name] = {
                'ids': top_10_ids,
                'details': top_10_details
            }
    
    # genre analysis
    for period_name, period_start in time_periods.items():

        period_listens = df_timestamps[df_timestamps['Timestamp'] >= period_start]
        period_genres = period_listens['Genres'].explode()
        genre_counts = period_genres.value_counts()
        top_10_genres = genre_counts.head(10)

        top_music[f'{period_name}_genres'] = {
            'ids': top_10_genres.index.tolist(),
            'details': [{'Genre': genre} for genre in top_10_genres.index.tolist()]
        }
    
    return top_music, df_timestamps, df_tracks, df_artists, df_albums, df_genres

def sanitize_data(obj):
    """
    recursively sanitize data -> make it JSON serialisable
    reference: https://stackoverflow.com/questions/33900327/python-sanitize-data-in-json-before-sending
    """
    if isinstance(obj, dict):
        return {k: sanitize_data(v) for k, v in obj.items() 
                if v is not None and not (isinstance(v, float) and math.isnan(v))}
    elif isinstance(obj, list):
        return [sanitize_data(item) for item in obj 
                if item is not None and not (isinstance(item, float) and math.isnan(item))]
    elif isinstance(obj, float):
        return 'N/A' if math.isnan(obj) else obj
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item() if hasattr(obj, 'item') else obj
    return obj

@eel.expose
def process_file(filename, file_data):
    try:
        logger.info(f"Processing file: {filename}")
        logger.info(f"File data length: {len(file_data)} characters")
        
        content = base64.b64decode(file_data.split(',')[1])
        logger.info(f"Decoded content length: {len(content)} bytes")
        
        excel_sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        logger.info(f"Sheets found: {list(excel_sheets.keys())}")
        
        processed_sheets = {}
        
        # expected sheet names
        expected_sheets = ['timestamp', 'tracks', 'albums', 'artists', 'genres']
        
        # process sheets
        for expected_sheet in expected_sheets:
            matching_sheets = [name for name in excel_sheets.keys() if name.lower() == expected_sheet]
            
            if not matching_sheets:
                raise ValueError(f"Missing required sheet: {expected_sheet}")
            
            sheet_name = matching_sheets[0]
            df = excel_sheets[sheet_name]
            
            # column mappings
            sheets_columns = {
                'timestamp': ["Timestamp", "Track ID", "Album ID", "Artist ID"],
                'tracks': ["Song Name", "Track ID", "Song URL", "Track Image", "Artist"],
                'albums': ["Album", "Album ID", "Album Image", "Artist"],
                'artists': ["Artist", "Artist ID", "Artist Image"],
                'genres': ['Genre', 'Count']
            }
            
            # column mapping
            column_mapping = dict(zip(df.columns, sheets_columns[expected_sheet]))
            df = df.rename(columns=column_mapping)
            
            processed_sheets[expected_sheet] = df
        
        # get top music
        top_music, df_timestamps, df_tracks, df_artists, df_albums, df_genres = analyze_top_music(processed_sheets)
        df_tracks.set_index('Track ID', inplace=True)
        df_artists.set_index('Artist ID', inplace=True)
        df_albums.set_index('Album ID', inplace=True)
        logger.info("File processed successfully!")
        
        sanitized_top_music = sanitize_data(top_music)

        return {
            "success": True, 
            "message": "file processed successfully!", 
            "sheets": list(processed_sheets.keys()),
            "data": processed_sheets,
            "top_music": sanitized_top_music
        }
    except Exception as e:
        logger.error(f"error processing file: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "success": False, 
            "message": str(e),
            "full_error": traceback.format_exc()
        }

logger.info("script ready. launching Eel...")

eel.start('index.html', size=(800, 600), mode='chrome', port=8000, host='localhost')
