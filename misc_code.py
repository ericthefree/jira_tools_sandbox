
comment_payload = {
    "body": {
      "jira_id": "BASH-19580",
      "jira_task_type": "Reproduced",
      "hotfix_comment": {
        "subject": "Update from 'srese-jira-hotfix-bash' lambda in 'Concur Integration Devscratch'.",
        "details": {
          "s3_hotfix_folder": "hotfix-payloads",
          "jira_component": "Outtask non-compiled ",
          "issue_type": "Hot Fix Request",
          "patch_priority": "3",
          "ddl_patch": "non-DDL",
          "hotfix_reason": "Scheduled Patch",
          "patch_name": "OuttaskPatch_Release_release_SU233__2023_10_10_214156",
          "hotfix_su_ver": 233,
          "stable_su_ver": 226,
          "prod_su_ver": 233,
          "s3_bucket": "srese-hotfix-data",
          "hotfix_s3_location": "hotfix-payloads/current_hotfix.json",
          "deploy_to_stable": False,
          "artifactory_path": "util-staging-local/t1/Patches/SU233/OuttaskPatch_Release_release_SU233__2023_10_10_214156.exe",
          "json_payload": {
              "HOTFIX_PATH": "util-staging-local/t1/Patches/SU233/OuttaskPatch_Release_release_SU233__2023_10_10_214156.exe", "HOTFIX_JIRA_ID": "BASH-19580", "deploy_to_stable": False
          },
          "env_stack": "ephemeral",
          "comment_text": "Hotfix for Jira ticket BASH-19580, SU233 with package: OuttaskPatch_Release_release_SU233__2023_10_10_214156.exe deploying to ephemeral via Hotfix Pipeline execution. Prod SU version is currently SU233."
        }
      }
    }
  }
test_value = comment_payload['body']['hotfix_comment']
hotfix_comment = json.dumps(comment_payload['body']['hotfix_comment']['subject']) + "\n\n" + json.dumps(comment_payload['body']['hotfix_comment']['details'], indent=4)

transition_payload = {
            'update': {
                'comment':[{
                    'add': {
                        'body': hotfix_comment
                    }
                }]
            },
            'transition': {
                'id': transition_to
            }
        }
# test_transition = transition_jira_ticket(JIRA_ID, "41", JIRA_PROD_URL, JIRA_TOKEN_KEY)

headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {JIRA_TOKEN_KEY}'
}

jira_full_url = JIRA_PROD_URL + "/issue/" + JIRA_ID + '/transitions'

transition_payload = {
        'update': {
            'comment': [{
                'add': {
                    'body': hotfix_comment
                }
            }]
        },
        'transition': {
            'id': '41'
        }
    }

test_transition_response = requests.post(url=jira_full_url, json=transition_payload, headers=headers)