#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
. $SCRIPT_DIR/utils.sh

#######################################
# Get tenant access token
# Arguments:
#   app_id
#   app_secret
# Outputs:
#   tenant_access_token
# Returns:
#   0 if success, non-zero on error
# References
#   https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
#######################################
get_feishu_tenant_access_token () {
    local USAGE="Usage: ${FUNCNAME[0]} APP_ID APP_SECRET"
    if (($# < 2)); then
        err "$USAGE"
        return 1
    fi
    local app_id="$1"
    local app_secret="$2"
    local req_data="{\"app_id\": \"${app_id}\", \"app_secret\": \"${app_secret}\"}"
    local response=""
    local status=0
    response=$(curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
        -H "Content-Type: application/json" \
        -d "$req_data")
    status=$?
    if (( $status != 0 )); then
        err "$response"
        return $status
    fi
    local code=$(echo $response | python3 -c "import sys, json; print(json.load(sys.stdin)['code'])")
    if (( $code != 0 )); then
        err "$response"
        return $code
    fi
    echo $response | python3 -c "import sys, json; print(json.load(sys.stdin)['tenant_access_token'])"
    return 0
}

#######################################
# Get the list of files in a feishu drive's folder
# Arguments:
#   folder_token
#   tenant_access_token
# Outputs:
#   json response from feishu
# Returns:
#   0 if success, non-zero on error
# References
#   https://open.feishu.cn/document/server-docs/docs/drive-v1/folder/list?appId=cli_a757f3c54b7a501c
#######################################
get_feishu_folder_files() {
    local USAGE="Usage: ${FUNCNAME[0]} FOLDER_TOKEN TENANT_ACCESS_TOKEN"
    if (($# < 2)); then
        err "$USAGE"
        return 1
    fi
    local folder_token="$1"
    local tenant_access_token="$2"
    local response=""
    local status=0
    local get_files_url="https://open.feishu.cn/open-apis/drive/v1/files?\
direction=DESC&folder_token=${folder_token}\
&order_by=EditedTime&page_size=200&user_id_type=open_id"
    response="$(curl -s -X GET "$get_files_url" \
        -H "Authorization: Bearer ${tenant_access_token}")"
    status=$?
    if (( $status != 0 )); then
        err "$response"
        return $status
    fi
    local code=$(echo $response | python3 -c "import sys, json; print(json.load(sys.stdin)['code'])")
    echo "$response"
    return $code
}

#######################################
# Download a file from feishu drive
# Arguments:
#   file_token
#   tenant_access_token
# Returns:
#   0 if success, non-zero on error
# References
#   https://open.feishu.cn/document/server-docs/docs/drive-v1/download/download
#######################################
download_feishu_file () {
    local USAGE="Usage: ${FUNCNAME[0]} FILE_TOKEN TENANT_ACCESS_TOKEN"
    if (($# < 2)); then
        err "$USAGE"
        return 1
    fi
    local file_token="$1"
    local tenant_access_token="$2"
    wget "https://open.feishu.cn/open-apis/drive/v1/files/$file_token/download" \
        --header="Authorization: Bearer ${tenant_access_token}"\
        --content-disposition --backups=1
    return $?
}
