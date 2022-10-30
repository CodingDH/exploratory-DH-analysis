import time
from urllib.parse import parse_qs
import pandas as pd
import requests
import os
from tqdm import tqdm
import apikey
import sys
sys.path.append("..")
from data_generation_scripts.utils import *
import shutil
import ast


auth_token = apikey.load("DH_GITHUB_DATA_PERSONAL_TOKEN")

auth_headers = {'Authorization': f'token {auth_token}','User-Agent': 'request'}

def get_actors(repo_df, repo_actors_output_path, users_output_path, get_url_field, is_stargazers):
    """Function to get all contributors to a list of repositories and also update final list of users.
    :param repo_df: dataframe of repositories
    :param repo_contributors_output_path: path to repo contributors file
    :param users_output_path: path to users file
    :param get_url_field: field in repo_df to get url from
    :param is_stargazers: boolean to indicate if we are getting stargazers
    :param is_forks: boolean to indicate if we are getting forks
    :param is_issues: boolean to indicate if we are getting issues
    returns: dataframe of repo contributors and unique users"""
    error_file_path = f"../data/error_logs/{repo_actors_output_path.split('/')[-1].split('.csv')[0]}_errors.csv"
    if os.path.exists(error_file_path):
        os.remove(error_file_path)

    temp_repo_actors_dir = f"../data/temp/{repo_actors_output_path.split('/')[-1].split('.csv')[0]}/"
    if os.path.exists(temp_repo_actors_dir):
        shutil.rmtree(temp_repo_actors_dir)
        os.makedirs(temp_repo_actors_dir)
    else:
        os.makedirs(temp_repo_actors_dir)  
    
    temp_users_dir = f"../data/temp/temp_users/"
    urls_df = pd.read_csv("../data/metadata_files/repo_url_cols.csv")
    original_auth_headers = auth_headers.copy()
    repo_progress_bar = tqdm(total=len(repo_df), desc="Getting Repo Actors", position=0)
    users_progress_bar = tqdm(total=0, desc="Getting Users", position=1)
    for _, row in repo_df.iterrows():
        try:
            repo_urls_metdata = urls_df[urls_df.url_type == get_url_field]
            counts_exist = repo_urls_metdata.count_type.values[0]
            if counts_exist != 'None':
                if (row[counts_exist] == 0):
                    repo_progress_bar.update(1)
                    continue
            dfs = []
            temp_repo_actors_path =  F"{row.full_name.replace('/','')}_repo_actors_{get_url_field}.csv" if 'full_name' in repo_df.columns else F"id_{str(row.id)}_repo_actors_{get_url_field}.csv"
            url = row[get_url_field].split('{')[0] + '?per_page=100&page=1' if '{' in row[get_url_field] else row[get_url_field] + '?per_page=100&page=1'

            url = url.replace('?', '?state=all&') if repo_urls_metdata.check_state.values[0] else url
            if is_stargazers:
                original_auth_headers = original_auth_headers | {'Accept': 'application/vnd.github.star+json'} 
            response = requests.get(url, headers=original_auth_headers)
            response_data = get_response_data(response, url)
            if len(response_data) == 0:
                repo_progress_bar.update(1)
                continue
            response_df = pd.json_normalize(response_data)
            dfs.append(response_df)
            while "next" in response.links.keys():
                time.sleep(120)
                query = response.links['next']['url']
                response = requests.get(query, headers=auth_headers)
                response_data = get_response_data(response, query)
                if len(response_data) == 0:
                    repo_progress_bar.update(1)
                    continue
                response_df = pd.json_normalize(response_data)
                dfs.append(response_df)
            data_df = pd.concat(dfs)
            if len(data_df) == 0:
                repo_progress_bar.update(1)
                continue
            else:
                repo_actors_df = data_df.copy()
                repo_actors_df['repo_id'] = row.id
                repo_actors_df['repo_url'] = row.url
                repo_actors_df['repo_html_url'] = row.html_url
                repo_actors_df['repo_full_name'] = row.full_name if 'full_name' in repo_df.columns else repo_df.repo_full_name
                repo_actors_df[get_url_field] = row[get_url_field]
                repo_actors_df.to_csv(temp_repo_actors_dir + temp_repo_actors_path, index=False)
                if 'login' in data_df.columns:
                    user_types = ['user.', 'owner.', 'author.']
                    for user_type in user_types:
                        if user_type in data_df.columns.tolist():
                            subset_cols = data_df.columns
                            subset_cols = [col for col in subset_cols if col.startswith(user_type.replace('.', ''))]
                            data_df = data_df[subset_cols]
                            data_df.columns = [col.split('.')[-1] for col in data_df.columns]
                            break
                    check_add_users(data_df, users_output_path, temp_users_dir, users_progress_bar, return_df=False)
                repo_progress_bar.update(1)
            
        except:
            print(f"Error on getting actors for {row.full_name}")
            error_df = pd.DataFrame([{'repo_full_name': row.full_name, 'error_time': time.time(), f'{get_url_field}': row[get_url_field]}])
            if os.path.exists(error_file_path):
                error_df.to_csv(error_file_path, mode='a', header=False, index=False)
            else:
                error_df.to_csv(error_file_path, index=False)
            repo_progress_bar.update(1)
            continue

    repo_actors_df = read_combine_files(temp_repo_actors_dir)
    if len(repo_actors_df) > 0:
        repo_actors_df.to_csv(repo_actors_output_path, index=False)
    else:
        repo_actors_df = pd.DataFrame()

    shutil.rmtree(temp_repo_actors_dir)
    repo_progress_bar.close()
    users_progress_bar.close()
    return repo_actors_df


def get_repos_user_actors(repo_df,repo_actors_output_path, users_output_path, rates_df, get_url_field, load_existing, is_stargazers):
    """Function to take a list of repositories and get any user activities that are related to a repo, save that into a join table, and also update final list of users.
    :param repo_df: dataframe of repositories
    :param repo_actors_output_path: path to repo actors file (actors here could be subscribers, stargazers, etc...)
    :param users_output_path: path to users file
    :param rates_df: dataframe of rate limits
    :param get_url_field: field in repo_df that contains the url to get the actors
    :param load_existing: boolean to load existing data
    :param is_stargazers: boolean to indicate if the actors are stargazers because stargazers have a slightly different Auth Headers
    :param is_forks: boolean to indicate if the actors are forks because forks have a slightly different column structure
    :param is_issues: boolean to indicate if the actors are issues because issues have a slightly different column structure
    returns: dataframe of repo contributors and unique users"""
    if load_existing:
        # if the file already exists, load it and return it
        repo_actors_df = pd.read_csv(repo_actors_output_path, low_memory=False)
        users_df = pd.read_csv(users_output_path, low_memory=False)
    else:
        # if the file doesn't exist, check that we have enough rate limits to get the data
        # calls_remaining = rates_df['resources.core.remaining'].values[0]
        # while len(repo_df[repo_df[get_url_field].notna()]) > calls_remaining:
        #     print('Not enough rate limits to get repo actors, waiting 15 minutes')
        #     time.sleep(3700)
        #     rates_df = check_rate_limit()
        #     calls_remaining = rates_df['resources.core.remaining'].values[0]
        # else:
        # if we have enough rate limits, first check if we already have an existing file with the repo actors so that we don't have to get the entirety each time
        if os.path.exists(repo_actors_output_path):
            repo_actors_df = pd.read_csv(repo_actors_output_path, low_memory=False)
            # unprocessed_actors = repo_df[~repo_df.url.isin(repo_actors_df.repository_url)] if is_issues else repo_df[~repo_df[get_url_field].isin(repo_actors_df[get_url_field])]
            if get_url_field in repo_actors_df.columns:
                unprocessed_actors = repo_df[~repo_df[get_url_field].isin(repo_actors_df[get_url_field])]
            else:
                unprocessed_actors = repo_df[~repo_df.url.isin(repo_actors_df.repository_url)] 
            error_file_path = f"../data/error_logs/{repo_actors_output_path.split('/')[-1].split('.csv')[0]}_errors.csv"
            if os.path.exists(error_file_path):
                error_df = pd.read_csv(error_file_path)
                unprocessed_actors = unprocessed_actors[~unprocessed_actors[get_url_field].isin(error_df[get_url_field])]
            if len(unprocessed_actors) > 0:
                new_actors_df = get_actors(unprocessed_actors, repo_actors_output_path, users_output_path, get_url_field, is_stargazers)
            else:
                new_actors_df = unprocessed_actors
            
            repo_actors_df = pd.concat([repo_actors_df, new_actors_df])
            repo_actors_df.to_csv(repo_actors_output_path, index=False)
        else:
            print('hitting else')
            repo_actors_df = get_actors(repo_df, repo_actors_output_path, users_output_path, get_url_field, is_stargazers)
    
    users_df = get_user_df(users_output_path)
    return repo_actors_df, users_df

if __name__ == "__main__":
    repo_df = pd.read_csv("../data/entity_files/repos_dataset.csv", low_memory=False)
    repo_actors_output_path = "../data/join_files/repo_stargazers_join_dataset.csv"
    users_output_path = "../data/entity_files/users_dataset.csv"
    rates_df = check_rate_limit()
    repo_actors_df, users_df = get_repos_user_actors(repo_df, repo_actors_output_path, users_output_path, rates_df, 'stargazers_url', load_existing=False)