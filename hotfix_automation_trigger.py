## Search criteria to find relevant sections
## GIT-PUBLISH -- Will find any relevant sections associated with retrieving or pushing to github

import json
import logging
import boto3
from botocore.exceptions import ClientError
from sys import exit
import os
import git
from git import Repo

# Setup logging format
logging.basicConfig(format="%(asctime)s - %(message)s", datefmt="%d-%b-%y %H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

s3 = boto3.resource("s3")  # Create s3 object
ssm_client = boto3.client("ssm")  # Create ssm object

## GIT Variables
branch = "RPL-hotfix"
local_dir = "/tmp"
local_repo = local_dir + "/Ansible-Windows"
varsFile = f"{local_repo}/.rpl/env-integration-stable.vars"

# Create lambda client object for triggering jira task execution lambda
lambda_client = boto3.client("lambda")


# GIT-PUBLISH - Retrieve the GitHub token to be used for cloning and pushing the commit back to GitHub
def get_github_token():
    # Retrieve GitHub token from Parameter Store
    try:
        github_token_param = ssm_client.get_parameter(
            Name="/outtask/hotfix/AmiBuild/GithubToken", WithDecryption=True
        )
        github_token = str(github_token_param["Parameter"]["Value"])
        logger.info(
            f"[!] Successfully retrieved GitHub Token from Parameter Store - Token: {github_token}"
        )
        return github_token
    except ClientError as error:
        logger.info(
            f"[!] Failed to retrieve GitHub Token from Parameter Store. Error: {error}"
        )
        return False


# GIT-PUBLISH - Clone GitHub repo locally
def clone_repo(remote_repo, local_dir, branch):
    # Change directory to /tmp folder
    os.chdir("/tmp")
    
    # Make a directory
    if not os.path.exists(os.path.join("Ansible-Windows")):
        os.makedirs("Ansible-Windows")
    
    logger.info(f"Directory created: {local_dir}/Ansible-Windows")
    logger.info("Cloning repo now...")
    
    try:
        clone_response = Repo.clone_from(
            remote_repo,
            "Ansible-Windows",
            branch=branch,
            env={"GIT_SSL_NO_VERIFY": "1"},
        )
        logger.info(
            f"Repo: {remote_repo}, branch: {branch} cloned to: {local_dir}/Ansible-Windows"
        )
    except git.exc.GitError as error:
        logger.error(f"Error occurred cloning repo: {remote_repo} with error: {error}")
        return error
    except git.exc.GitCommandError as gc_error:
        logger.error(
            f"Error occurred cloning repo: {remote_repo} with error: {gc_error}"
        )
        return gc_error
    except git.exc.CommandError as com_error:
        logger.error(
            f"Error occurred cloning repo: {remote_repo} with error: {com_error}"
        )
        return com_error
    
    return clone_response


# GIT-PUBLISH - Function to push repo
def git_push(local_repo, commit_message):
    repo = Repo(local_repo + "/.git")
    repo.git.add(update=True)
    repo.index.commit(
        commit_message,
    )
    origin = repo.remote(name="origin")
    origin.push(env={"GIT_SSL_NO_VERIFY": "1"})


def upload_to_s3(json_payload):
    logger.info(
        f"Attempting to upload current_hotfix.json to: {json_payload['comment_detail']['hotfix_s3_location']}"
    )
    try:
        s3.Bucket(json_payload["comment_detail"]["s3_bucket"]).put_object(
            Key=json_payload["comment_detail"]["hotfix_s3_location"],
            Body=json_payload["json_upload_payload"],
        )
        s3_upload_response = [
            True,
            f"current_hotfix.json payload was uploaded to S3 location: "
            f"{json_payload['comment_detail']['hotfix_s3_location']}.\n"
            f"Outtask-Hotfix-AMI-Builds pipeline will trigger execution.\n\n",
        ]
    except ClientError as s3_error:
        error_code = s3_error.response["Error"]["Code"]
        logger.error(
            f"An error occurred during s3 upload of current_hotfix.json. Error Code: {error_code}. Pipeline "
            f"execution may have failed if current_hotfix.json upload fails. Script execution will terminate!",
            exc_info=True,
        )
        s3_upload_response = [
            False,
            f"An error occurred during s3 upload of current_hotfix.json. Error Code: "
            f"{error_code}\nPipeline execution will not be triggered. Script execution "
            f"will terminate!",
        ]
        logger.error(
            f"S3 upload failed: error occurred during upload of current_hotfix.json with error_code: {error_code}"
        )
    logger.info(f"Upload of current_hotfix.json response: {s3_upload_response}")
    return s3_upload_response


def update_jira_ticket(jira_execution_payload):
    # Comment data for the hotfix ticket
    hotfix_comment = {
        "body": {
            "jira_id": jira_execution_payload["jira_id"],
            "jira_task_type": jira_execution_payload["jira_task_type"],
            "hotfix_comment": {
                "subject": jira_execution_payload["subject_text"],
                "details": {},
            },
        }
    }
    hotfix_comment["body"]["hotfix_comment"]["details"] = jira_execution_payload[
        "comment_detail"
    ]
    logger.info(f"Hotfix comment payload: {hotfix_comment}")
    
    # Invoke jira task lambda to comment in the jira ticket
    if jira_execution_payload["jira_id"]:
        try:
            jira_task_invoke_response = lambda_client.invoke(
                FunctionName="arn:aws:lambda:us-west-2:478142941285:function:srese_execute_jira_task",
                InvocationType="RequestResponse",
                Payload=json.dumps(hotfix_comment, indent=4),
            )
            jira_task_invoke_response = [
                True,
                json.load(jira_task_invoke_response["Payload"]),
            ]
            logger.info(
                f'Response from Jira ticket update for Jira: {jira_execution_payload["jira_id"]}:\n'
                f"{jira_task_invoke_response}"
            )
            return jira_task_invoke_response
        except ClientError as ce:
            logger.error(
                f"An error occurred while updating Jira {jira_execution_payload['jira_id']} with comment.\nERROR: {ce}",
                exc_info=True,
            )
            return [False, ce]
    else:
        logger.error("Jira ID not found. No comment will be added.")
        exit("Build Terminated: No valid Jira ID found.")
    return [False, "No Jira ID"]


def lambda_handler(event, context):
    # Default to trigger hotfix
    trigger_rpl = False
    
    # Set default s3 hotfix folder for hotfix payload based on test_run
    s3_bucket = "srese-hotfix-data"  # Set default s3 bucket for hotfix payload
    
    test_run = False  # Set test_run default
    
    default_s3_hotfix_folder = "hotfix-payloads"  # Set default location for s3 hotfix folder

    # Initialize values for variables being set in the script
    env_stack = hotfix_s3_location = deployment_window = hotfix_comment_text = ""
    
    # Set up the json data for parsing info from it
    try:
        event_body = json.loads(json.loads(event.get("body", {}))["body"])
    except ValueError as error:
        logger.error(
            f'Lambda event does not contain a key "body" within the event.\nCheck the log for the event '
            f"payload output. Script will terminate after echoing the payload to the console.\nERROR: "
            f"{error}",
            exc_info=True,
        )
        logger.info(
            f"Lambda event trigger payload received:\n{json.dumps(event, indent=4)}"
        )
        exit(
            'Lambda event does not contain key value for "body" in the Lambda event payload. Script terminated!'
        )
    else:
        logger.info(f"Payload data for Lambda event: {json.dumps(event)}")
    
    # Pull the details for the issue from the event
    try:
        issue_data = event_body["issue"]
    except ValueError as ve:
        logger.error(
            f"No issue details detected in event_body:\n{event_body}.\nScript will terminate!\nERROR: {ve}"
        )
        exit("Build Terminated: No issue details detected in event_body.")
    else:
        logger.info(f"Issue details parsed from Lambda event: {issue_data}")

    #### GIT ACTIONS - Cloning repo for local use
    gh_token = get_github_token()
    
    if gh_token:  # Clone hotfix branch locally
        # Define variables for GitHub actions
        logger.info("GitHub token found. Cloning repo.")
        
        remote_repo = f"https://{gh_token}@github.concur.com/SRESE/ansible-windows.git"
        
        local_file = local_repo + "/current_hotfix.json"
        commit_message = "Committing to initiate RPL build"
        
        clone_response = clone_repo(remote_repo, local_dir, branch)
        logger.info(f"clone_repo response: {clone_response}")
        logger.info(f"[+] {branch} successfully cloned")
    else:
        logger.error("GitHub token not retrieved successfully.")
    
    # Checking for test_run value in event payload
    # If test_run is set in test_values data set, test_run value set from test_values data
    # If test_run not set in test_values and exists at root of payload, test_run value set from event payload
    # If test_run not set in either location, test_run set to true by default because test_values exists and
    #   assumes it's a test run
    if "test_values" in event:
        # If either of these key's exists in event payload, set different loc for default_s3_hotfix_folder
        # If either of these key's exist, they would only exist if test event payload being used
        default_s3_hotfix_folder = "test_hotfix_payloads"
        if "test_values" in event:
            if "test_run" in event["test_values"]:
                test_run = event["test_values"]["test_run"]
            elif "test_run" in event:
                test_run = event["test_run"]
            else:
                # Set test_run to true by default if test_values exists and test_run not set
                test_run = True
    elif "test_run" in event:
        default_s3_hotfix_folder = "test_hotfix_payloads"
        test_run = event["test_run"]
    else:
        default_s3_hotfix_folder = default_s3_hotfix_folder
        test_run = False
    logger.info(
        f"default_s3_hotfix_folder set to: {default_s3_hotfix_folder}, test_run set to: {test_run}"
    )
    
    deploy_to_stable = False  # Set release week value to False
    transition_name = (
        "comment"  # Set default value for updating Jira ticket to "comment"
    )
    patch_name = "invalid_patch"  # Set default value for patch_name
    if "upload_s3" in event:
        upload_s3 = event["upload_s3"]
    else:
        upload_s3 = False
    
    # Initialize Jira payload for executing Jira ticket update
    jira_task_payload = {
        "jira_id": "",
        "jira_task_type": "comment",  # Default value should be comment.
        "subject_text": "Update from 'srese-jira-hotfix-bash' lambda in 'Concur Integration Devscratch'.",
        "comment_detail": {},
    }
    
    jira_task_payload["comment_detail"]["s3_hotfix_folder"] = default_s3_hotfix_folder
    
    # Script execution to gather payload data from event payload starts here
    logger.info(
        "START: Building payload data for current_hotfix.json to upload to S3 and trigger pipeline."
    )
    
    # Check if test_values payload exists in the event and set the values
    if "test_values" in event:
        try:
            jira_id = event["test_values"][
                "test_jira_id"
            ]  # Setting jira_id from test_values
            jira_task_payload["jira_id"] = jira_id
            logger.info(f"Jira ID parsed from test_values: {jira_id}")
        except ValueError as no_jira_id:
            logger.error(
                f"No value for jira_id found in test_values nor in event issue_data. Script execution will terminate!\n"
                f"ERROR: {no_jira_id}",
                exc_info=True,
            )
            exit("Build Terminated: No valid Jira ID found in text_values payload.")
        logger.info(
            f"TEST RUN:\ntest_values detected in payload: {event['test_values']}.\nJira ID parsed from test event: "
            f"{jira_id}.\ncurrent_s3_hotfix_folder for test run: "
            f"{jira_task_payload['comment_detail']['s3_hotfix_folder']}"
        )
    
    # Set jira_id from issue_data when jira_id not set and test_run is False
    elif not test_run:
        try:
            jira_task_payload["jira_id"] = jira_id = issue_data["key"]  # Set the jira_id from the event when not set by test event
        except ValueError as no_jira_id_value:
            logger.error(
                f"No value for jira_id was found event issue_data. Script execution will terminate! ERROR: "
                f"{no_jira_id_value}",
                exc_info=True,
            )
            exit("Build Terminated: No valid Jira ID found.")
        else:
            logger.info(f"Jira ID parsed from event: {jira_id}")

        # Check for transition_name
        try:
            transition_name = event_body["transition"]["transitionName"]
        except ValueError as transition_value_error:
            logger.error(f"Error getting transition_name.\n\nERROR: transition_value_error")
        else:
            jira_task_payload["jira_task_type"] = transition_name
        
        # Get list of components and add to dictionary
        try:
            jira_component = issue_data["fields"]["components"][0]["name"]
        except ValueError as jira_component_value_error:
            jira_task_payload["comment_detail"][
                "jira_component"
            ] = "No component detected."
            logger.info(
                f'No value for component detected. jira_component value set to: "No component detected."'
            )
        else:
            jira_task_payload["comment_detail"]["jira_component"] = jira_component
            # Check if jira_component value is DBUpdate or Config and exit if true
            if jira_component.lower() == "dbupdate":
                logger.error(
                    f"Jira component: {jira_component} parsed from event not an expected component for hotfix "
                    f"pipeline execution. Script execution terminated!"
                )
                hotfix_comment_text += (
                    f"Jira component: {jira_component} parsed from event not an expected "
                    f"component for hotfix.\nScript execution terminated!"
                )
                jira_task_payload["comment_detail"][
                    "comment_text"
                ] = hotfix_comment_text
                update_jira_ticket(jira_task_payload)
                exit(
                    f"Component type: {jira_component} not valid for executing hotfix pipeline. Script will terminate!"
                )
            elif jira_component.lower() == "config":
                upload_s3 = False  # Making sure pipeline is not triggered.
                logger.info(
                    f"Jira component: {jira_component} type 'Config' detected.\nExpected action is to transition the "
                    f"Jira ticket and not trigger the pipeline."
                )
                hotfix_comment_text += (
                    f"Jira component: {jira_component} type 'Config'.\nExpected action is to "
                    f"transition the Jira ticket and not trigger the pipeline."
                )
                jira_task_payload["comment_detail"][
                    "comment_text"
                ] = hotfix_comment_text
                update_jira_ticket(jira_task_payload)
                exit(
                    f"Jira component: {jira_component} detected. Hotfix pipeline will not be triggered. Script "
                    f"execution will now be terminated!"
                )
            else:
                logger.info(
                    f"Jira component: {jira_component} expected component type for triggering Hotfix Pipeline. Script "
                    f"will continue."
                )
                
        # Get and set issue type
        try:
            issue_type = issue_data["fields"]["issuetype"]["name"]
        except ValueError as issue_type_value_error:
            upload_s3 = False  # Make sure pipeline does not trigger
            logger.error(
                "No issue_type detected. Pipeline execution will not be triggered."
            )
            hotfix_comment_text += (
                "No issue_type detected as Hotfix. Hotfix pipeline was not triggered."
            )
            jira_task_payload["comment_detail"]["comment_text"] = hotfix_comment_text
            update_jira_ticket(jira_task_payload)
            exit(
                f"No or invalid issue_type detected in payload. Hotfix pipeline not triggered. Script will terminate!"
                f"\n\nERROR: {issue_type_value_error}"
            )
        else:
            logger.info(f"Hotfix type parsed from event: {issue_type}")
            jira_task_payload["comment_detail"]["issue_type"] = issue_type
        
        # Get and set DDL patch
        try:
            ddl_patch = issue_data["fields"]["customfield_12813"]["value"]
        except ValueError as ddl_patch_value_error:
            logger.error(f"No value detected for ddl_patch type. Script will continue.\n\n"
                         f"ERROR: {ddl_patch_value_error}")
        else:
            jira_task_payload["comment_detail"]["ddl_patch"] = ddl_patch
    else:
        # If you reach this point in the script run, then default value for test_run set to 'True' which is invalid
        logger.error(
            'Hotfix Pipeline execution script unexpected error.\nNo test_values entered, but value for "test_run" is'
            'set.\nPlease verify the default value for "test_run" was not set in the lambda '
            "script.\n\nScript will now terminate."
        )
        exit(
            "Default value for 'test_run' set, but no test_values detected. Script will terminate!"
        )
    
    # Get the value for which jira env the call came from
    jira_url = issue_data["self"]
    
    # Get and set the patch name
    if test_run:
        try:
            patch_name = event["test_values"]["test_patch_name"]
        except ValueError as patch_name_value_error:
            logger.error(f'Error getting test_patch_name.\n\nERROR: {patch_name_value_error}')
    else:
        try:
            patch_name = issue_data["fields"]["customfield_10582"]
        except ValueError as patch_name_value_error:
            logger.error(f'Error getting patch_name.\n\nERROR: {patch_name_value_error}')
        else:
            logger.info(f"Hotfix patch name parsed from event: {patch_name}")

    if patch_name == "invalid_patch":
        logger.error("No value for 'patch_name' found. Script cannot continue.")
        exit('No value for "patch_name" in found. Script will terminate!')
    
    # Check that the patch_name value is not blank and exit if it is
    if "jira.concur.com" in jira_url and ".exe" in patch_name:
        patch_name = issue_data["fields"]["customfield_10582"][:-4]
        logger.info(f"Hotfix patch name parsed from event: {patch_name}")
        jira_task_payload["comment_detail"]["patch_name"] = patch_name
    
    if "outtaskpatch" in patch_name.lower():
        # Parse SU version from patch name
        hotfix_su_ver = int(patch_name[31:34])
        jira_task_payload["comment_detail"]["hotfix_su_ver"] = hotfix_su_ver
        
        # Get stable and prod SU versions for validating hotfix deployment
        stable_su_param = ssm_client.get_parameter(
            Name="/stable/AmiBuild/SuVersion", WithDecryption=True
        )
        prod_su_param = ssm_client.get_parameter(
            Name="/prod2/AmiBuild/SuVersion", WithDecryption=True
        )
        
        stable_su_ver = int(stable_su_param["Parameter"]["Value"][2:])
        prod_su_ver = int(prod_su_param["Parameter"]["Value"][2:])
        logger.info(
            f"Stable SU version: {stable_su_param}\n"
            f"Prod SU version: {prod_su_param}"
        )
        
        jira_task_payload["comment_detail"]["stable_su_ver"] = stable_su_ver
        jira_task_payload["comment_detail"]["prod_su_ver"] = prod_su_ver
        
        # This portion sets whether we will deploy to stable or the alternate stack (currently ephemeral)
        # If the prod su_ver is greater than the hotfix su_ver, we will not deploy the hotfix (invalid)
        # During release week validation we do not want to continue hotfix deployments to stable except
        # in the case where the hotfix su_ver is the same version as the current stable su_ver
        # (this is a case where pending su release needs a hotfix tested before it's released to prod)
        # If the stable su_ver is equal to the hotfix su_ver, then we will always deploy to stable (True)
        # If the (hotfix_su_ver is equal to stable_su_ver) and (hotfix_su_ver is equal to or greater than
        # prod_su_ver, then set deploy_to_stable equal to True, otherwise set to False
        
        # The end resulting logic is simply 'if hotfix_su_ver == stable_su_ver then deploy_to_stable covers
        # all scenario's for setting the route as of this update
        
        if not test_run:
            if prod_su_ver > hotfix_su_ver:
                logger.error(
                    "SU version of the hotfix package less than SU version in prod. Script will terminate. Pipeline "
                    "execution will not continue!"
                )
                hotfix_comment_text += (
                    f"Hotfix SU version: {hotfix_su_ver} less than Prod SU version: "
                    f"{prod_su_ver}. Script terminated!"
                )
                jira_task_payload["comment_detail"][
                    "comment_text"
                ] = hotfix_comment_text
                update_jira_ticket(jira_task_payload)
                logger.error(
                    f"Hotfix SU version: {hotfix_su_ver} less than Prod SU version: {prod_su_ver}. Hotfix pipeline "
                    f"execution will not continue."
                )
                exit(
                    f"Hotfix SU version: {hotfix_su_ver} less than Prod SU version: {prod_su_ver}. Script will "
                    f"terminate!"
                )
            else:
                deploy_to_stable = False
                env_stack = "ephemeral"
                upload_s3 = False
                trigger_rpl = True
        else:
            try:
                deploy_to_stable = event["test_values"]["test_deploy_to_stable"]
            except ValueError as deploy_value_error:
                logger.error(f'Error getting deploy_to_stable.\n\nERROR: {deploy_value_error}')

            try:
                env_stack = event["test_values"]["test_env_stack"]
            except ValueError as env_stack_value_error:
                logger.error(f'Error getting deploy_to_stable.\n\nERROR: {env_stack_value_error}')
        
        logger.info(
            f"Environment stack for deployment: {env_stack}.\nupload_s3 value: {upload_s3}"
        )
        
        hotfix_s3_location = f"{default_s3_hotfix_folder}/current_hotfix.json"
        jira_task_payload["comment_detail"]["s3_bucket"] = s3_bucket
        jira_task_payload["comment_detail"]["hotfix_s3_location"] = hotfix_s3_location
        jira_task_payload["comment_detail"]["deploy_to_stable"] = deploy_to_stable
        hotfix_comment_text += (
            f"Hotfix for Jira ticket {jira_id}, SU{hotfix_su_ver} with package: {patch_name}.exe "
            f"deploying to {env_stack} via Hotfix Pipeline execution. Prod SU version is "
            f"currently SU{prod_su_ver}."
        )
        
        # Set location for s3 key based on which Jira location is used
        if "jira.concur.com" not in jira_url:
            logging.error(
                f"Unexpected Jira location found: {jira_url}. Script execution will terminate!"
            )
            hotfix_comment_text += f"Unexpected Jira location found: {jira_url}.\nScript execution will terminate!"
            jira_task_payload["comment_detail"]["comment_text"] = hotfix_comment_text
            exit("Build Terminated: Jira unexpected Jira URL!")
        
        # Set the patch extended path in artifactory
        jira_task_payload["comment_detail"]["artifactory_path"] = (
            f"util-staging-local/t1/Patches/SU{hotfix_su_ver}/" f"{patch_name}.exe"
        )
        
        # Create current_json.json file and set values
        json_payload_data = {
            "HOTFIX_PATH": jira_task_payload["comment_detail"]["artifactory_path"],
            "HOTFIX_JIRA_ID": jira_task_payload["jira_id"],
            "deploy_to_stable": jira_task_payload["comment_detail"]["deploy_to_stable"],
        }
        clean_json_data = json.dumps(json_payload_data)
        current_json_data = json.dumps(json_payload_data, indent=4)
        jira_task_payload["comment_detail"]["json_payload"] = clean_json_data
        jira_task_payload["json_upload_payload"] = current_json_data
        logger.info(f"Payload for current_hotfix.json: {current_json_data}")
    else:
        upload_s3 = False
        env_stack = "no_stack"
        deploy_to_stable = "no_deploy"
        trigger_rpl = False
    
    jira_task_payload["comment_detail"]["env_stack"] = env_stack
    jira_task_payload["comment_detail"]["deploy_to_stable"] = deploy_to_stable
    
    # GIT-PUBLISH - Updating env variable for RPL AMi builds
    def update_yaml():
        vars_to_write = (
            f"\nexport HOTFIX_PATH={jira_task_payload['comment_detail']['artifactory_path']}\n"
            f"export JIRA={jira_task_payload['jira_id']}"
        )
        with open(varsFile, "r+") as vars_file:
            vars_file.truncate()
            vars_file.seek(0)
            vars_file.write("AUTODEPLOY=true \n")
            vars_file.write("ValidateGAMI=false \n")
            vars_file.write(f"SU_VERSION={hotfix_su_ver} \n")
            vars_file.writelines(vars_to_write)
        
        vars_file.close()
    
    # Trigger rpl if set to True
    if trigger_rpl:
        # GIT-PUBLISH - Writing current_hotfix.json to local repo for commit
        try:
            update_yaml()
        except ValueError as git_write:
            logger.error(
                f"[!] Unable to write variable file for commit - Error: {git_write}"
            )
        else:
            logger.info(f"[+] Variable file saved successfully")
            try:
                git_push(local_repo, commit_message)
            except ValueError as git_commit_error:
                logger.error(
                    f"[!] Failed to commit {local_file} - Error: {git_commit_error}"
                )
            else:
                logger.info(f"[+] Commit Successful. Check RPL for build progress ")
    
    # Create the current_hotfix.json file and write the data to s3
    if upload_s3:
        # Check folder value if test_run is true to not be the s3 trigger location and file
        if (
            test_run
            and jira_task_payload["comment_detail"]["hotfix_s3_location"]
            == f"hotfix-payloads/"
               f"current_hotfix.json"
        ):
            # Set the folder value again
            jira_task_payload["comment_detail"]["hotfix_s3_location"] = (
                f"test_hotfix_payloads" f"/current_hotfix.json"
            )
            logger.info(
                f"Value for s3 upload test_folder location set: "
                f'{jira_task_payload["comment_detail"]["hotfix_s3_location"]}'
            )
    elif test_run and not upload_s3:
        logger.info(
            f"TEST EXECUTION RUN of LAMBDA!!!\ncurrent_hotfix.json payload upload attempt to S3 location: "
            f"{hotfix_s3_location} will NOT be executed.\nOuttask-Hotfix-AMI-Builds pipeline execution "
            f"will not be executed."
        )
        jira_task_payload["comment_detail"]["s3_upload_response"] = (
            f"TEST EXECUTION RUN of LAMBDA: "
            f"payload upload attempt to S3 location: "
            f"{hotfix_s3_location} was NOT executed."
            f"\nOuttask-Hotfix-AMI-Builds pipeline execution "
            f"will not be executed.\n\n"
        )
    else:
        logger.info(
            f"No valid hotfix to trigger hotfix pipeline. current_hotfix.json payload attempt to s3 location: "
            f"{hotfix_s3_location} will not be executed.\nOuttask-Hotfix-AMI Builds pipeline execution "
            f"will not be executed."
        )
    
    # Check that the comment text has been set.
    if "comment_text" not in jira_task_payload["comment_detail"]:
        jira_task_payload["comment_detail"]["comment_text"] = hotfix_comment_text
    
    # Update the Jira ticket
    jira_update_response = update_jira_ticket(jira_task_payload)
    
    if jira_update_response[0]:
        logger.info(f"Jira update succeeded. Jira response:{jira_update_response[1]}")
    else:
        logger.error(
            f"Jira update failed. Jira response error: {jira_update_response[1]}"
        )
    
    logger.info(f"!!!*** End of script execution! ***!!!")
    
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(event),
        "jira_url": jira_url,
        "current_json_data": jira_task_payload["comment_detail"]["json_payload"],
        "deploy_to_stable": jira_task_payload["comment_detail"]["deploy_to_stable"],
        "hotfix_comment": jira_task_payload["comment_detail"]["comment_text"],
        "jira_update_response": jira_update_response[1],
    }
