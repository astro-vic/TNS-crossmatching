""" A script to crossmatch TNS transients with KKO FRBs and plot the 2D Gaussian elliptical distribution
@author: Yuxin Dong
last edited: Oct 24, 2024 """
import numpy as np
import pandas as pd
import json
import time
import requests
import os
import sys
from collections import OrderedDict

from astropy.coordinates import SkyCoord
import ligo.skymap.plot # KEEP: needed for projections in matplotlib
from astropy import units as u

from scipy.stats import chi2
from astropy.io import ascii

from matplotlib.patches import Ellipse
import matplotlib.pyplot as plt
import matplotlib


import argparse

def parser():
    # Create an argument parser
    parser = argparse.ArgumentParser(description='Script to run TNS queries on FRBs.')

    parser.add_argument("--single", action='store_true', help="Indicate if the query is for a single FRB object.")

    parser.add_argument("--filename", type=str, help="a list of FRBs for a batch query.")
    parser.add_argument("--name", type=str, help="FRB TNS name of the single FRB object.")
    parser.add_argument("--ra", type=float, help="Right Ascension of the single FRB object.")
    parser.add_argument("--dec", type=float, help="Declination of the single FRB object.")
    parser.add_argument("--theta", type=float, help="Theta value (make sure you add a negative sign) of the single FRB object.")
    parser.add_argument("--a", type=float, help="Semi-major axis for the single FRB object.")
    parser.add_argument("--b", type=float, help="Semi-minor axis for the single FRB object.")

    parser.add_argument("--radius", type=float, default=3.0, help="Radius for the query (default is 3.0).")

    return parser.parse_args()


def check_tns_api_keywords():
    for key in ['TNS_BOT_ID','TNS_BOT_NAME','TNS_API_KEY']:
        if key not in os.environ.keys():
            raise Exception(f'Add {key} to your environmental variables.')


def format_to_json(source):
    try:
        parsed = json.loads(source)
        data = parsed.get('data')
        reply = data.get('reply')
        if reply is None:
            print("Error: 'reply' key not found in JSON.")
            return None
        return reply
    except json.JSONDecodeError as e:
        print("Error decoding JSON:", e)
        return None


def search(json_list):
    try:
        search_url = 'https://www.wis-tns.org/api/get/search'
        bot_id = os.environ['TNS_BOT_ID']
        bot_name = os.environ['TNS_BOT_NAME']
        api_key = os.environ['TNS_API_KEY']
        headers = {
            'User-Agent': f'tns_marker{{"tns_id":{bot_id}, "type":"bot", "name":"{bot_name}"}}'}
        json_file = OrderedDict(json_list)
        search_data = {'api_key': api_key, 'data': json.dumps(json_file)}
        response = requests.post(search_url, headers=headers, data=search_data)
        return response
    except Exception as e:
        return [None, 'Error message : \n' + str(e)]


def tns_query(ra, dec, radius, frb_name, units='arcmin', initial_delay=10, max_delay=300, outfile='query_results_final.txt'):

    '''
   Queries transients in TNS at the FRB position with a specfied radius.

    Parameters: 
    -----------
    ra (float): right ascension of the FRB  
    dec (float): declination of the FRB
    radius (float): search radius in arcmin; default is 3
    frb_name (str): TNS name of the FRB
    
    Returns: 
    --------
    query output: dict
        a dictionary of transients found within the search radius near an FRB position
    '''

    search_obj = [("ra", ra), ("dec", dec), ("radius", radius), ("units", units)]
    max_retries = 8
    delay = initial_delay
    attempt = 0
    results_dict = {}
    while True:
        response = search(search_obj)
        if response.status_code == 429:
            if attempt < max_retries:
                print(f"Throttled. Retrying in {delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay = min(delay * 2, max_delay)  # Exponential backoff
                attempt += 1
            else:
                print("All retry attempts failed. Unable to get a successful response.")
                break
        else:
            response.raise_for_status()
            result = format_to_json(response.text)
            if result:
                for item in result:
                    if item['prefix'] == 'FRB':
                            print(f"Skipping object with FRB prefix: {item['objname']}")
                            continue 
                    obj_id = item['objid']
                    results_dict[obj_id] = {
                        'FRB Name': frb_name,
                        'Object Name': item['objname'],
                        'Prefix': item['prefix'],
                        'Object ID': obj_id
                    }
                print(f"Results for {frb_name} have been added to the dictionary.")
            else: 
                print(f"No Results found for {frb_name}")
            break
            # if you want to write them into a file
            #if result:
            #    with open(outfile, 'a') as f:
            #        for item in result:
            #            f.write(f"FRB Name: {frb_name}, Object Name: {item['objname']}, Prefix: {item['prefix']}, Object ID: {item['objid']}\n")
            #    print(f"Reply content for {frb_name} has been written to {outfile}")
            #    return outfile
    return results_dict

# this is for getting metadata
def set_bot_tns_marker():
    bot_id = os.environ['TNS_BOT_ID']
    bot_name = os.environ['TNS_BOT_NAME']
    tns_marker = 'tns_marker{"tns_id": "' + bot_id + '", "type": "bot", "name": "' + bot_name + '"}'
    return tns_marker


def get_metadata(objname):
    """
    Obtain all metadata (z, discovery date, classification, etc.) for a given transient.

    Parameters:
    objname (str): name of the transient

    Returns:
    json: metadata associated with the transient
    """
    TNS = "sandbox.wis-tns.org"
    url_tns_api = "https://" + TNS + "/api/get" 
    get_url = url_tns_api + "/object"
    api_key = os.environ['TNS_API_KEY']
    tns_marker = set_bot_tns_marker()
    headers = {'User-Agent': tns_marker}
    get_obj = [("objname", objname), ("objid", "")]
    json_file = OrderedDict(get_obj)
    get_data = {'api_key': api_key, 'data': json.dumps(json_file)}
    response = requests.post(get_url, headers=headers, data=get_data)
    if response.status_code == 200:
        return json.loads(response.text, object_pairs_hook=OrderedDict)
    else:
        print(f"Error fetching metadata for {objname}: {response.status_code}")
        return None


def read_final_catalog(filename):
    f = ascii.read(filename)

    filtered_f = f[f['include'] == 'yes']
    
    name = np.array(filtered_f['name'].data)
    ra = np.array(filtered_f['ra_frb'].data)
    dec = np.array(filtered_f['dec_frb'].data)
    theta = np.array(filtered_f['theta'].data)
    b = np.array(filtered_f['b_err'].data)
    a = np.array(filtered_f['a_err'].data)
    #DM = filtered_f['DM'].data
  
    return name, ra, dec, theta, a, b


def cov_matrix(a, b, theta):

    """
    Calculate the covariance matrix for a 2D ellipse.
    
    Parameters:
    a (float): Semi-major axis of the ellipse
    b (float): Semi-minor axis of the ellipse
    theta (float): Position angle of the ellipse in degrees
    
    Returns:
    np.ndarray: 2x2 covariance matrix
    """

    # Convert theta to radians
    theta_rad = np.radians(theta + 90)  # Adjust angle for correct orientation
    # Rotation matrix for an ellipse with position angle
    R = np.array([[np.cos(theta_rad), -np.sin(theta_rad)], 
                  [np.sin(theta_rad), np.cos(theta_rad)]])
    # Diagonal matrix with square of semi-major and semi-minor axes
    D = np.diag([a**2, b**2])
    # Covariance matrix
    covariance_matrix = R @ D @ R.T
    return covariance_matrix


def mahalanobis_distance(point, frbcenter, cov_matrix):
    """
    Calculate the Mahalanobis distance between a given point and the center.
    effectively the Z-score in 1D, and it can be a proxy for how many sigma away you are from the mean.

    Parameters:
    point (array-like): The point for which to calculate the distance (should be [RA, Dec]).
    frbcenter (array-like): The center point, usually the mean [RA, Dec].
    cov_matrix (array-like): The covariance matrix of the data.

    Returns:
    float: The Mahalanobis distance.
    """

    # the frbcenter in this case is the 'mean'
    diff = np.array(point) - np.array(frbcenter)
    
    # correction term for spherical geometry
    correction = diff[0] * (1 / np.cos(np.radians(point[1])))
    diff_corrected = np.array([correction, diff[1]])
    inv_cov_matrix = np.linalg.inv(cov_matrix)
    md = np.sqrt(diff_corrected.T @ inv_cov_matrix @ diff_corrected)
    
    return md


def percentile(mahalanobis_distance, df=2):
    p_value = chi2.cdf(mahalanobis_distance**2, df)
    return p_value

def gauss_contour(frbcenter, cov_matrix, semi_major, transient_name,
                  transient_position=None, levels=[0.68, 0.95, 0.99]):
    
    """
    Plot Gaussian contours around a given FRB center based on its covariance matrix.
    
    This function computes and visualizes the Gaussian contours (ellipses) 
    that represent the uncertainty in the position of the FRB as defined by 
    its covariance matrix. Then, it plots the position of the transient along with 
    the Mahalanobis distance from the FRB center.
    
    Parameters:
    frbcenter (Astropy SkyCoord): The central position of the FRB.
    cov_matrix (array-like): The covariance matrix representing the uncertainties in the FRB's position.
    semi_major (float): The semi-major axis of the Gaussian ellipse in degrees.
    transient_name (str): The name of the transient source.
    transient_position (Astropy SkyCoord): Transient position.
    levels: List of confidence levels for the contours (default: [0.68, 0.95, 0.99]).
    """
    
    eigvals, eigvecs = np.linalg.eigh(cov_matrix)
    order = eigvals.argsort()[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    
    width, height = 2 * np.sqrt(eigvals)
    theta = np.degrees(np.arctan2(*eigvecs[:, 0][::-1]))
    threshold = chi2.ppf(0.9999, df=2)
    
    fig = plt.figure(figsize=(6, 6))
    # 2 arcmins size, quite arbitrary so can be changed
    size = 2 #semi_major*60*80
    ax = plt.axes(
    projection='astro zoom',
    center=frbcenter,
    radius=size*u.arcmin)

    # Plot FRB center
    ax.plot(frbcenter.ra.deg, frbcenter.dec.deg, 
        transform=ax.get_transform('world'), color='black', marker='x', 
        markersize=5)
    
    cmap = matplotlib.colormaps.get_cmap('viridis')

    for i, level in enumerate(levels):
        chi_square_val = chi2.ppf(level, 2)
        color = cmap(i / len(levels))
        ellipse = Ellipse(
            xy=(frbcenter.ra.deg, frbcenter.dec.deg),
            width=width * np.sqrt(chi_square_val),
            height=height * np.sqrt(chi_square_val),
            angle=theta,
            edgecolor=color,
            fc='None',
            lw=2,
            label=f'{int(level*100)}%',
            transform=ax.get_transform('world')
        )
        ax.add_patch(ellipse)
    
    if transient_position is not None:
        ax.plot(transient_position.ra.deg, transient_position.dec.deg, 
                transform=ax.get_transform('world'), 
                color='#fb5607', marker='o', label=transient_name)
        
        
        md = mahalanobis_distance([transient_position.ra.deg, transient_position.dec.deg],
                                  [frbcenter.ra.deg, frbcenter.dec.deg], cov_matrix)
        pt = percentile(md)
        ax.annotate(f'{(1-pt)*100:.3f}%', xy=[transient_position.ra.deg, transient_position.dec.deg],
                    xytext=(12, 12), textcoords='offset points')     
        
    ax.set_xlabel('RA (J2000)', fontsize=14)
    ax.set_ylabel('DEC (J2000)', fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(False)
    plt.tight_layout()
    plt.savefig(f'{transient_name}_gaussian_map.png')


def main(filename, name, ra, dec, theta, a, b, radius, single_obj=False):

    """
    Main function to query the TNS for transient data; can be batched or a single object search.
    Parameters:
    filename: The path to the ASCII file containing the catalog data (only used if single_obj is False).
    name (str): FRB name (only used if single_obj is True).
    ra (float): FRB RA in degrees 
    dec (float): FRB Dec in degrees
    theta: Position Angle in degrees (only used if single_obj is True).
    a: semi-minor axis in degrees (only used if single_obj is True).
    b: semi-minor axis in degrees (only used if single_obj is True).
    radius: The search radius (arcminute).
    single_obj: Boolean indicating whether to perform a query for a single object (True) or multiple (False).

    Returns:
    trans_results: dictionary 
    trans_metadata: dictionary
    2D Gaussian map: png
    """ 
     
    trans_results = {}
    if not single_obj:
        name, ra, dec, theta, a, b = read_final_catalog(filename)
        for n, r, d in zip(name, ra, dec):
            frb_results = tns_query(r, d, frb_name=n, radius=radius)
            trans_results.update(frb_results)
    else:
        frb_results = tns_query(ra, dec, frb_name=name, radius=radius)
        trans_results.update(frb_results)

    #grab all the metadata from TNS for the transients
    trans_metadata = {}
    for obj_id, data in trans_results.items():
        objname = data['Object Name']
        FRBname = data['FRB Name']
        print(f'Fetching metadata for object: {objname}')
        metadata = get_metadata(objname)
        # fill free to add anything other info you want from TNS
        if metadata:
            data = metadata.get('data',{}); reply = data.get('reply',{})
            type = reply.get('object_type',{})
            formatted_data = {
                'frbname': FRBname,
                'objname': reply.get('objname', ''),
                'prefix': reply.get('name_prefix'),
                'type': type.get('name', ''),
                'radeg': reply.get('radeg', ''),
                'decdeg': reply.get('decdeg', ''),
                'ra': reply.get('ra', ''),
                'dec': reply.get('dec', ''),
                'redshift': reply.get('redshift', ''),
                'hostname': reply.get('hostname', ''),
                'host_redshift': reply.get('host_redshift'),
            }
            trans_metadata[obj_id] = formatted_data

    if single_obj:
        for obj_id, data in trans_metadata.items():
            cov = cov_matrix(a, b, theta)
            transient_pos = SkyCoord(ra=data['radeg'], dec=data['decdeg'], unit='deg')
            frbcenter = SkyCoord(ra=ra, dec=dec, unit='deg')
            gauss_contour(frbcenter, cov, a, data['objname'], transient_pos)
            break  # Exit the loop after finding a match
    else:
        # now we plot the 2D Gaussian maps 
        for n, r, d, t, a, b in zip(name, ra, dec, theta, a, b):
            for obj_id, data in trans_metadata.items():
                if data['frbname'] == n:
                    # semi-minor goes first
                    cov = cov_matrix(a,b,t)
                    transient_pos = SkyCoord(ra=data['radeg'],dec=data['decdeg'],unit='deg')
                    frbcenter = SkyCoord(ra=r,dec=d,unit='deg')
                    gauss_contour(frbcenter, cov, a, data['objname'], transient_pos)
                        
                    # Save the plot as a PNG file
                    plt.savefig(f'{n}_gaussian_map.png')

if __name__ == "__main__":
    # Verify that you've added these to your env var 
    args = parser()
    check_tns_api_keywords()
    if args.single:
        if args.ra is None or args.dec is None or args.theta is None or args.a is None or args.b is None:
            print("Error: Missing parameters for single object query.")
            exit(1)
        matched_transient_data = main(filename=None,
                                      name=args.name, 
                                      ra=args.ra, 
                                      dec=args.dec,
                                      theta=args.theta, 
                                      a=args.a, b=args.b, radius=args.radius, single_obj=True)
    else:
        frb_file = args.filename #sys.argv[1]
        matched_transient_data = main(frb_file, name=None, ra=None, dec=None, theta=None, a=None, b=None,
                                      radius=args.radius, single_obj=False)