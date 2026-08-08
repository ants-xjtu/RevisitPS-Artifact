#!/bin/bash

#######################################
# Upload a file to aliyun oss
# Arguments:
#   host name (e.g., oss-cn-shanghai.aliyuncs.com)
#   bucket name
#   access key id
#   access key secret
#   file to upload, a path
#   (optional) destination path to upload to, a path
# Returns:
#   0 if file is uploaded, non-zero on error.
#######################################
function aliyun_upload() {
    local USAGE="Usage: ${FUNCNAME[0]} HOST BUCKET ACCESS_KEY_ID ACCESS_KEY_SECRET SRCFILE [DSTFILE]"
    if (($# < 5)); then
        echo $USAGE >&2
        return 1
    fi
    local host="$1"
    local bucket="$2"
    local accesskey_id="$3"
    local accesskey_secret="$4"
    local srcfile="$5"
    local dstfile="$(basename $srcfile)"
    if (($# >= 6)); then
        dstfile="$6"
    fi

    local osshost=$bucket.$host

    if [ ! -f $srcfile ]; then
        echo "File \"$srcfile\" does not exist" >&2
        return 1
    fi

    local resource="/${bucket}/${dstfile}"
    local contenttype=$(file --mime --brief ${srcfile} | awk -F ";" '{print $1}')
    local datevalue="$(TZ=GMT env LANG=en_US.UTF-8 date +'%a, %d %b %Y %H:%M:%S GMT')"
    local stringtosign="PUT\n\n${contenttype}\n${datevalue}\n${resource}"
    local signature=$(echo -en $stringtosign | openssl sha1 -hmac ${accesskey_secret} -binary | base64)

    local url=https://${osshost}/${dstfile}
    echo "Upload ${srcfile} to ${url}"

    curl -i -q -X PUT -T "${srcfile}" \
        -H "Host: ${osshost}" \
        -H "Date: ${datevalue}" \
        -H "Content-Type: ${contenttype}" \
        -H "Authorization: OSS ${accesskey_id}:${signature}" \
        ${url}
}


#######################################
# Download a file from aliyun oss
# Arguments:
#   host name (e.g., oss-cn-shanghai.aliyuncs.com)
#   bucket name
#   access key id
#   access key secret
#   file to upload, a path
#   (optional) destination path to upload to, a path
# Returns:
#   0 if file is uploaded, non-zero on error.
#######################################
function aliyun_download() {
    local USAGE="Usage: ${FUNCNAME[0]} HOST BUCKET ACCESS_KEY_ID ACCESS_KEY_SECRET SRCFILE [DSTFILE]"
    if (($# < 5)); then
        echo $USAGE >&2
        return 1
    fi
    local host="$1"
    local bucket="$2"
    local accesskey_id="$3"
    local accesskey_secret="$4"
    local srcfile="$5"
    local dstfile=$(basename $srcfile)
    if (($# >= 6)); then
        dstfile="$6"
    fi

    local osshost=$bucket.$host


    local resource="/${bucket}/${dstfile}"
    local contenttype=""
    local datevalue="$(TZ=GMT env LANG=en_US.UTF-8 date +'%a, %d %b %Y %H:%M:%S GMT')"
    local stringtosign="GET\n\n${contenttype}\n${datevalue}\n${resource}"
    local signature=$(echo -en $stringtosign | openssl sha1 -hmac ${accesskey_secret} -binary | base64)

    local url=https://${osshost}/${srcfile}
    echo "Download ${url} to ${dstfile}"

    curl --create-dirs \
        -H "Host: ${osshost}" \
        -H "Date: ${datevalue}" \
        -H "Content-Type: ${contenttype}" \
        -H "Authorization: OSS ${accesskey_id}:${signature}" \
        ${url} -o ${dstfile}
}
