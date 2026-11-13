#!/bin/sh
set -eu

image_prefix=${1:?Usage: sh scripts/build_images.sh ghcr.io/owner/name version [--with-browser]}
image_version=${2:?Provide an immutable version tag}

docker build -t "$image_prefix-api:$image_version" .
docker push "$image_prefix-api:$image_version"

if [ "${3:-}" = "--with-browser" ]; then
    docker build -f browser/Dockerfile -t "$image_prefix-browser:$image_version" .
    docker push "$image_prefix-browser:$image_version"
fi
