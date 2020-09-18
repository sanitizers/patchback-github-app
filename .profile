export GIT_TAGS=$(git ls-remote --tags git://github.com/sanitizers/patchback-github-app.git | grep -v '\^{}$' | grep -E "^${SOURCE_VERSION}")
export LAST_TAG_VERSION=$(echo "${GIT_TAGS}" | awk '{print$2}' | sed 's#^refs/tags/##;s#^v##' | grep -v '[abcepr]' | tail -n1)
export LAST_TAG_VERSION="${LAST_TAG_VERSION:-0.1}"

TAG_MATCHES_REF=
echo $GIT_TAGS | grep -E "/v?${LAST_TAG_VERSION}$" | grep -E "^${SOURCE_VERSION}\s" >/dev/null && TAG_MATCHES_REF=true
if [[ -z "${SOURCE_VERSION}" || -z ${TAG_MATCHES_REF} ]]
then
    export DEV_SUFFIX=.dev0
else
    export DEV_SUFFIX=
fi


export SETUPTOOLS_SCM_PRETEND_VERSION="${LAST_TAG_VERSION}${DEV_SUFFIX}+g${SOURCE_VERSION:-unknown}"
