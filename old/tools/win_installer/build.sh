
DIR="$( cd "$( dirname "$0" )" && pwd )"
source "$DIR"/_base.sh

function main {
    # started from the wrong env -> switch
    if [ -n "$MSYSTEM" ] && [ $(echo "$MSYSTEM" | tr '[A-Z]' '[a-z]') != "$MINGW" ]; then
        echo ">>>>> MSYSTEM=${MSYSTEM} - SWITCHING TO ${MINGW} <<<<"
        "/${MINGW}.exe" "$0"
        echo ">>>>> DONE WITH ${MINGW} ?? <<<<"
        exit $?
    fi
}

main "$@";
