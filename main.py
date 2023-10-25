import requests
import json
import logging

# Setup logging format
logging.basicConfig(format="%(asctime)s - %(message)s", datefmt="%d-%b-%y %H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

JIRA_PROD_URL = 'https://jira.concur.com/rest/api/2/'
JIRA_TOKEN_URL = 'https://jira.concur.com/rest/pat/latest/tokens'
JIRA_TOKEN_KEY = 'ODg2NzIyNTM3NDg0OhVbjG66AUUmnU0BOLYT9O+rtWkk'
JIRA_TOKEN_KEY_DS = 'NjU5OTI3NDQ1Mjk4OjpLqwlxOlWhQNhlV8c8dBEZ7Ciu'
JIRA_TOKEN_KEY_DS2 = 'NjUxMDM0NzEzNTE1Ot7UTZ3eSLqDJcOwBuFD25dWPtg8'
JIRA_TOKEN_KEY_JIRA_TOKEN_SDA = 'MjcxNDE0MDE1NTA3Ov1ZIJMYI9iSLY5poY9rXIyfjC9b'
JIRA_TOKEN_KEY_SDA_JIRA = 'ODk1NjgzOTM4MTk2OrPoawbhrIuCA6PdA8IV0De6IGo5'
JIRA_TOKEN_KEY_JIRA_SDA_PERSONAL = 'NjUxMDM0NzEzNTE1Ot7UTZ3eSLqDJcOwBuFD25dWPtg8'
JIRA_PROJECT_KEY = 'BASH'
JIRA_API_URL = "https://jira.concur.com/rest/api/latest/issue/"
JIRA_ID = "BASH-19568"
HOTFIX_WORKFLOW_TRANSITION_ORDER = [
    'Open',
    'Pending Repro (QA)',
    'Pending CM',
    'Pending QA',
    'Pending Review',
    'Pending Approval',
    'Pending Deploy',
    'Closed'
]


def get_project_features(jira_url, jira_token_key, jira_project_key):
    
    jira_headers = {
        'Authorization': f'Bearer {jira_token_key}',
        'Content-Type': 'application/json'
    }
    
    jira_full_url = jira_url + "project/" + jira_project_key
    jira_response = requests.get(jira_full_url, headers=jira_headers)
    jira_json_response = json.loads(jira_response.text)
    # jira_project_id = jira_json_response['id']
    # jira_project_name = jira_json_response['name']
    # jira_project_category_id = jira_json_response['projectCategory']['id']
    
    logger.info(f'Jira features:\n\n'
                f'{json.dumps(json.loads(jira_response.text), sort_keys=True, indent=4, separators=(",", ": "))}')
    
    return jira_json_response


def get_project_permissions(jira_url, jira_token_key, jira_project_key):
    
    jira_headers = {
        'Authorization': f'Bearer {jira_token_key}',
        'Content-Type': 'application/json'
    }
    
    jira_full_url = jira_url + "project/" + jira_project_key + "/securitylevel"
    jira_response = requests.get(jira_full_url, headers=jira_headers)
    jira_json_response = json.loads(jira_response.text)
    
    return jira_json_response


def get_project_workflow(jira_url, jira_token_key, jira_project_key):
    jira_transition_statuses = {}
    
    jira_headers = {
        'Authorization': f'Bearer {jira_token_key}',
        'Content-Type': 'application/json'
    }
    
    jira_full_url = jira_url + "project/" + jira_project_key + "/statuses"
    jira_response = requests.get(jira_full_url, headers=jira_headers)
    jira_json_response = json.loads(jira_response.text)
    
    for current_status in jira_json_response:
        jira_transition_statuses[current_status['name']] = {
            'id': current_status['id'],
            'statuses': current_status['statuses']
        }
    return jira_transition_statuses


def get_workflow_transitions(jira_url, jira_token_key):
    jira_headers = {
        'Authorization': f'Bearer {jira_token_key}',
        'Content-Type': 'application/json'
    }
    
    jira_full_url = jira_url + 'workflow/search'
    
    jira_response = requests.get(jira_full_url, headers=jira_headers)
    jira_workflow_transitions = json.loads(jira_response.text)
    
    return jira_workflow_transitions


def get_jira_token_properties(jira_url, current_token):
    """
    Get the properties of the token being requested to evaluate
    :param jira_url: The url for Jira where requesting the properties of the token.
    :param current_token: The token values for which requesting from Jira.
    :return: token_properties ~ The properties of the token being requested.
    """

    token_properties = {}
    
    # set the headers and body for the POST request
    headers = {
        'Authorization': f'Bearer {current_token}',
        'Content-Type': 'application/json'
    }

    jira_response = requests.get(jira_url, headers=headers)
    token_prop_list = json.loads(jira_response.content)

    return token_prop_list


def get_jira_current_status(jira_url, jira_id, jira_token):
    headers = {
        'Authorization': f'Bearer {jira_token}',
        'Content-Type': 'application/json'
    }
    
    jira_full_url = jira_url + jira_id
    
    jira_response = requests.get(jira_full_url, headers=headers)
    jira_details = json.loads(jira_response.text)
    jira_issue_fields = jira_details['fields']
    jira_transition_state = {
        'jira_status_name': jira_issue_fields['status']['name'],
        'jira_status_id': jira_issue_fields['status']['id'],
        'jira_issue_type': jira_issue_fields['issuetype']['name']
    }
    
    return jira_transition_state
    

def get_workflow_statuses(issue_type, list_of_statuses, jira_token):
    jira_statuses = {}
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {jira_token}'
    }
    
    for current_status in list_of_statuses[issue_type]['statuses']:
        jira_statuses[current_status['name']] = {
            'status_id': current_status['id']
        }
        
    return jira_statuses


def transition_jira_ticket(jira_id, transition_to_id, jira_url, jira_token):
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {jira_token}'
    }
    
    jira_full_url = jira_url + "/issue/" + jira_id + '/transitions'
    
    hotfix_comment = {
        "subject": "Test Transition Comment",
        "details": {
            "transition_comment": "The Jira ticket is being transitioned."
        }
    }
    
    transition_payload = {
        'update': {
            'comment': [{
                'add': {
                    'body': hotfix_comment
                }
            }]
        },
        'transition': {
            'id': transition_to_id
        }
    }
    
    
    jira_transition_response = requests.post(url=jira_full_url, json=transition_payload, headers=headers)
    
    return jira_transition_response


def get_transitions_by_status(transition_id, jira_token, jira_id, jira_url):
    transition_id_payload = {}

    params = {
        "id": transition_id
    }
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {jira_token}'
    }
    
    full_url = jira_url + f"issue/{jira_id}/transitions"
    
    available_ids = json.loads(requests.get(url=full_url, headers=headers, params=params).text)['transitions']
    
    for current_id in available_ids:
        transition_id_payload[current_id['name']] = current_id['id']
    
    return transition_id_payload


def get_jira_issue_payload_by_id(jira_id, jira_url, jira_token):
    full_url = f"{jira_url}/issue/{jira_id}"
    
    jira_headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {jira_token}'
    }
    
    jira_response = requests.get(url=full_url, headers=jira_headers)
    
    jira_issue_payload = json.dumps(json.loads(jira_response.text), sort_keys=True, indent=4, separators=(",", ": "))
    
    return jira_issue_payload


jira_issue_payload = get_jira_issue_payload_by_id("BASH-19588", JIRA_PROD_URL, JIRA_TOKEN_KEY)
jira_features = get_project_features(JIRA_PROD_URL, JIRA_TOKEN_KEY, JIRA_PROJECT_KEY)
jira_permissions = get_project_permissions(JIRA_PROD_URL, JIRA_TOKEN_KEY, JIRA_PROJECT_KEY)
jira_transitions = get_project_workflow(JIRA_PROD_URL, JIRA_TOKEN_KEY, JIRA_PROJECT_KEY)
jira_token_properties = get_jira_token_properties(JIRA_TOKEN_URL, JIRA_TOKEN_KEY)
# jira_token_properties_ds = get_jira_token_properties(JIRA_TOKEN_URL, JIRA_TOKEN_KEY)
# jira_token_properties_ds2 = get_jira_token_properties(JIRA_TOKEN_URL, JIRA_TOKEN_KEY)
jira_transition_state = get_jira_current_status(JIRA_API_URL, JIRA_ID, JIRA_TOKEN_KEY)
jira_transitions_statuses = get_workflow_statuses(jira_transition_state['jira_issue_type'], jira_transitions, JIRA_TOKEN_KEY)
jira_transition_to_ids = get_transitions_by_status(jira_transition_state['jira_status_id'], JIRA_TOKEN_KEY, JIRA_ID, JIRA_PROD_URL)

transition_jira_ticket = transition_jira_ticket(JIRA_ID, "41", JIRA_PROD_URL, JIRA_TOKEN_KEY)

print()
