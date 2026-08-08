#!/bin/bash

#######################################
# Set the color of echo messages
# Arguments:
#   color name (red/yellow/green/blue/nocolor)
# Returns:
#   0 if color is set, non-zero on error.
#######################################
function set_echocolor() {
    local NOCOLOR='\033[0m'
    local RED='\033[0;31m'
    local YELLOW='\033[0;33m'
    local GREEN='\033[0;32m'
    local BLUE='\033[0;34m'
    local USAGE="Usage: ${FUNCNAME[0]} COLORNAME WHETHER_TO_STDERR"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local colorname=$1
    local color_varname=$(echo $colorname | tr '[:lower:]' '[:upper:]')
    if [ -z ${!color_varname+x} ]; then
        err "Unknown color: $colorname"
        return 1
    fi
    echo -en "${!color_varname}"
}

#######################################
# Print error message
# Arguments:
#   Error message
# Outputs:
#   Date+Colorized message
#######################################
function err() {
    set_echocolor green
    echo -n "[$(date +'%Y-%m-%d %H:%M:%S')] "
    set_echocolor red
    echo -e "$*" >&2
    set_echocolor nocolor
}

#######################################
# Check whether the current user is root
# Returns:
#   0 if the current user is root, non-zero otherwise.
#######################################
function checkroot() {
    if [[ "${EUID}" -ne 0 ]]; then
        return 1
    fi
}

#######################################
# Check whether date is valid
# Arguments:
#   Date
# Returns:
#   0 if valid, non-zero else
#######################################
check_date () {
    local USAGE="Usage: ${FUNCNAME[0]} DATE"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local date="$1"
    if [[ $input_date =~ ^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1])$ ]]; then
        return 0
    else
        return 1
    fi
}

#######################################
# Expand tilde(~) from a path
# Arguments:
#   variable name
# Returns:
#   0 if success, non-zero on error
#######################################
function expanduser() {
    local USAGE="Usage: ${FUNCNAME[0]} VARNAME"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local varname=$1
    eval echo ${!varname}
}

#######################################
# Get the NIC device name to reach a given host
# Arguments:
#   Host name
# Outputs:
#   NIC name
# Returns:
#   0 if success, non-zero on error
#######################################
get_out_dev () {
    local USAGE="Usage: ${FUNCNAME[0]} HOST_NAME"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local host="$1"
    local ip="$(python3 -c "import socket; print(socket.gethostbyname(\"$host\"))")"
    ip route get $ip | grep -o "dev.*" | cut -d ' ' -f 2
}

#######################################
# Get the physical NIC device name to reach a given host
# Arguments:
#   Host name
# Outputs:
#   NIC name
# Returns:
#   0 if success, non-zero on error
#######################################
get_phy_out_dev () {
    local USAGE="Usage: ${FUNCNAME[0]} HOST_NAME"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local host="$1"
    local ip="$(python3 -c "import socket; print(socket.gethostbyname(\"$host\"))")"
    local dev="$(ip route get $ip | grep -o "dev.*" | cut -d ' ' -f 2)"
    if [[ "$dev" == "lo" ]]; then
        echo $dev
        return
    fi
    while [ ! -e /sys/class/net/$dev/device ]; do
        local drv="$(ethtool -i $dev | grep driver | cut -d' ' -f2)"
        if [[ "$drv" == 'bridge' ]]; then
            ping -c 1 -i 0.2 $ip > /dev/null || err "ping $ip exits with error"
            local dmac=$(ip neigh show $ip | grep -o "lladdr.*" | cut -d ' ' -f 2)
            if [[ -z "$dmac" ]]; then
                err "Cannot resolve the mac address of $ip"
                return 1
            fi
            dev=$(bridge fdb get $dmac br $dev | grep -o "dev.*" | cut -d ' ' -f 2)
        else
            err "Unknown device type: $drv"
            return 1
        fi
    done
    echo $dev
}

#######################################
# Get the source ip addr to reach a given host
# Arguments:
#   Host name
# Outputs:
#   ip address
# Returns:
#   0 if success, non-zero on error
#######################################
get_out_srcip () {
    local USAGE="Usage: ${FUNCNAME[0]} HOST_NAME"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local host="$1"
    local dstip="$(python3 -c "import socket; print(socket.gethostbyname(\"$host\"))")"
    local srcip="$(ip route get $dstip | grep -o "src.*" | cut -d ' ' -f 2)"
    echo $srcip
}

#######################################
# Convert an ip address to an integer
# Arguments:
#   ip address (e.g., 202.117.0.20)
# Outputs:
#   an integer
#######################################
ip2int () {
    local USAGE="Usage: ${FUNCNAME[0]} IP"
    if (($# < 1)); then
        err "$USAGE"
        return 1
    fi
    local ipaddr="$1"
    local i1 i2 i3 i4
    IFS=. read -r i1 i2 i3 i4 <<< "$ipaddr"
    echo $(((i1 << 24) + (i2 << 16) + (i3 << 8) + i4))
}

#######################################
# Whether an ip address is in a CIDR
# Arguments:
#   ip address (e.g., 202.117.0.20)
#   CIDR (e.g., 202.117.0.0/24)
# Returns:
#   0 if in CIDR, 1 if not
#######################################
is_ip_in_cidr () {
    local USAGE="Usage: ${FUNCNAME[0]} IP CIDR"
    if (($# < 2)); then
        err "$USAGE"
        return 255
    fi
    local ipaddr="$1"
    local cidr="$2"
    local network mask
    IFS=/ read -r network mask <<< "$cidr"
    local ipaddr_dec=$(ip2int $ipaddr)
    local netip_dec=$(ip2int $network)
    local mask_dec=$(((0xffffffff >> mask) ^ 0xffffffff))
    [[ $((ipaddr_dec & mask_dec)) -eq $((netip_dec & mask_dec)) ]] && return 0 || return 1
}

#######################################
# Whether the current network is in xjtu net
# Returns:
#   0 if in xjtu net, non-zero if not
#######################################
is_xjtu_net () {
    local xjtu_nets=$(cat <<-END
    202.117.0.0/16
    115.154.0.0/16
    10.181.0.0/16
END
)
    local srcip=$(get_out_srcip www.xjtu.edu.cn)
    for xjtu_net in $xjtu_nets; do
        is_ip_in_cidr $srcip $xjtu_net && return 0
    done
    return 1

}

#######################################
# Get Operating System name
# Outputs:
#   OS name (macos/ubuntu)
#######################################
get_os_name () {
    case $(uname -s) in
        Darwin) echo 'macos';;
        Linux) cat '/etc/os-release' |  grep -i '^id=' | awk -F= '{print $2}' ;;
    esac
}

#######################################
# Get CPU architecture
# Outputs:
#   CPU architecture (amd64/arm64)
#######################################
get_cpu_arch () {
    case $(uname -m) in
        i386)   echo '386' ;;
        i686)   echo '386' ;;
        x86_64) echo 'amd64' ;;
        aarch64) echo 'arm64' ;;
        arm64) echo 'arm64' ;;
    esac
}

#######################################
# Get CPU Microarchitecture levels
# Ref: https://en.wikipedia.org/wiki/X86-64#Microarchitecture_levels
# Outputs:
#   v2 or v3 or v4
#######################################
get_cpu_microarch_level () {
    case $(uname -s) in
        Linux)
            ld.so --help | grep -i supported | awk '{print $1}' | cut -d '-' -f3 | sort | tail -1
            ;;
        Darwin)
            echo 'Unknown'
            ;;
        *)
            echo 'Unknown'
            ;;
    esac
}

#######################################
# Quietly install package with homebrew
# Arguments:
#   Package names
#######################################
brew_install_quiet () {
    for formula in $@; do
        brew list $formula &> /dev/null || brew install $formula
    done
}

#######################################
# Install packages in different Operating systems
# Arguments:
#   Package names
# Returns:
#   0 if success, non-zero on error
#######################################
install_pkg () {
    if (($# == 0)); then
        return 1
    fi
    local os_name=$(get_os_name | tr '[:upper:]' '[:lower:]')
    case $os_name in
        ubuntu | debian)
            sudo apt update -y
            sudo apt install -y $@
            ;;
        arch)
            sudo pacman -Su --noconfirm --needed $@
            ;;
        macos)
            brew_install_quiet $@
            ;;
        centos)
            sudo yum install -y $@
            ;;
        *)
            err "Unknown OS: $os_name"
            return 1
    esac
}


#######################################
# Backup directory by moving this directory to the archive directory
# Arguments:
#  Directory path to backup
#  Archive directory name
# Returns:
#   0 if success, non-zero on error
#######################################
backup_dir () {
    local USAGE="Usage: ${FUNCNAME[0]} DIRECTORY [ARCHIVE_DIRECTORY]"
    if (($# < 1)); then
        err $USAGE
        return 1
    fi
    local dirname="$1"
    local archivedir="$(dirname $dirname)/archives"
    if (($# >= 2)); then
        archivedir="$2"
    fi
    if [ -e "$dirname" ] && [ -n "$(ls $dirname)" ]; then
        local postfix=$(date +'%Y%m%d%H%M%S')
        mkdir -p $archivedir
        mv $dirname $archivedir/$(basename $dirname)-$postfix
    fi
}

#######################################
# Bind the rx irq of a network device of a cpu
# Args:
#   Network interface name
#   CPU ID to bind the rx irq to
# Returns:
#   0 if success, non-zero on error
#######################################
bind_rxirq_to_cpu () {
    local USAGE="Usage: ${FUNCNAME[0]} DEVNAME CPU_ID"
    if (($# < 2)); then
        err $USAGE
        return 1
    fi
    local devname="$1"
    local cpuid="$2"
    # `irqbalance` tries to automatically balance IRQs to CPUs
    # and it may overwrite the CPU affinity settings.
    pgrep irqbalance && sudo systemctl stop irqbalance.service
    for irqnum in $(grep $devname /proc/interrupts | awk -F':' '{print $1}'); do
        sudo bash -c "echo $cpuid > /proc/irq/$irqnum/smp_affinity_list"
    done
}

#######################################
# Remove a qdisc from all devices
# Args:
#   qdisc name
# Returns:
#   0 if success, non-zero on error
#######################################
remove_qdisc () {
    local USAGE="${FUNCNAME[0]} QDISC"
    if (($# < 1)); then
        err $USAGE
        return 1
    fi
    local qdisc="$1"
    for dev in $(ip link show | grep '^[0-9]\+' | cut -d':' -f2); do
        if [[ -n "$(tc qdisc show dev $dev | cut -d' ' -f2 | grep "^${qdisc}$")" ]]; then
            sudo tc qdisc del dev $dev root
        fi
    done
}

#######################################
# Remove a packet scheduling kernel module
# Args:
#   kernel module name
#   qdisc name of this kernel module
# Returns:
#   0 if success, non-zero on error
#######################################
remove_sch_mod () {
    local USAGE="${FUNCNAME[0]} MODULE_NAME QDISC_NAME"
    if (($# < 2)); then
        err $USAGE
        return 1
    fi
    local modname="$1"
    local qdisc="$2"
    local n_used=$(lsmod | grep "^${modname}\\s" | awk '{print $3}')
    if [[ -n "$n_used" ]]; then
        if (($n_used > 0)); then
            remove_qdisc $qdisc
        fi
        sudo rmmod $modname
    fi
}

#######################################
# Find which ip address the host is listen on a specified port
# Args:
#   port number
# Outputs:
#   IP address
#######################################
find_tcp_listen_ip() {
    local USAGE="${FUNCNAME[0]} PORT_NUMBER"
    if (($# < 1)); then
        err $USAGE
        return 1
    fi
    local listen_port="$1"
    local ipaddr=$(sudo lsof -nP -iTCP:$listen_port -sTCP:LISTEN -Fn | grep $listen_port | awk -F"n" '{print $2}' | awk -F ":" '{print $1}')
    if [[ "$ipaddr" == "*" ]] || [[ "$ipaddr" == "0.0.0.0" ]]; then
        echo "127.0.0.1"
    else
        echo $ipaddr
    fi
}

#######################################
# Find which ip address the host is listen on a specified port
# Args:
#   port number
# Outputs:
#   IP address
#######################################
find_udp_listen_ip() {
    local USAGE="${FUNCNAME[0]} PORT_NUMBER"
    if (($# < 1)); then
        err $USAGE
        return 1
    fi
    local listen_port="$1"
    local ipaddr=$(sudo lsof -nP -iUDP:$listen_port -Fn | grep $listen_port | awk -F"n" '{print $2}' | awk -F ":" '{print $1}')
    if [[ "$ipaddr" == "*" ]] || [[ "$ipaddr" == "0.0.0.0" ]]; then
        echo "127.0.0.1"
    else
        echo $ipaddr
    fi
}
