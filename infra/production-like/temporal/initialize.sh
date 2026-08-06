#!/bin/sh

set -eu

ADDRESS=${TEMPORAL_ADDRESS:-temporal:7233}
NAMESPACE=${TEMPORAL_NAMESPACE:-gaia-production-like}

until temporal operator cluster health --address "$ADDRESS" >/dev/null 2>&1; do
  sleep 2
done

if ! temporal operator namespace describe \
  --namespace "$NAMESPACE" --address "$ADDRESS" >/dev/null 2>&1; then
  temporal operator namespace create \
    --namespace "$NAMESPACE" \
    --retention 7d \
    --address "$ADDRESS"
fi

until temporal operator namespace describe \
  --namespace "$NAMESPACE" --address "$ADDRESS" >/dev/null 2>&1; do
  sleep 1
done

# Namespace registration and the Search Attribute frontend are eventually
# consistent. `namespace describe` can succeed for a freshly-created namespace
# while `search-attribute list` still returns "namespace not found"; wait for
# the exact API the next step uses instead of treating registration as enough.
until temporal operator search-attribute list \
  --namespace "$NAMESPACE" --address "$ADDRESS" >/dev/null 2>&1; do
  sleep 1
done

for attribute in GaiaOrganization GaiaScenarioId GaiaRunStatus; do
  if ! temporal operator search-attribute list \
    --namespace "$NAMESPACE" \
    --address "$ADDRESS" | grep -q "$attribute"; then
    temporal operator search-attribute create \
      --namespace "$NAMESPACE" \
      --name "$attribute" \
      --type Keyword \
      --address "$ADDRESS"
  fi
done
