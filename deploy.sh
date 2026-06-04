#!/usr/bin/env bash
# Deploy the Formula E simulator to Cloud Run.
# Idempotent: creates Pub/Sub topic if missing, creates service account if missing,
# grants necessary roles, and deploys (or updates) the service.

set -euo pipefail

# --- Config (override via env) ---
SERVICE_NAME="${SERVICE_NAME:-fe-simulator}"
REGION="${REGION:-us-central1}"
TOPIC_NAME="${TOPIC_NAME:-fe-telemetry}"
SA_NAME="${SA_NAME:-fe-simulator-sa}"
FRAMES_BUCKET="${FRAMES_BUCKET:-class-demo}"
FRAMES_PATH="${FRAMES_PATH:-formula-e/r10/simulator/frames_v3.jsonl.gz}"
REPLAY_SPEED_MULTIPLIER="${REPLAY_SPEED_MULTIPLIER:-1.0}"
AUTO_RESTART="${AUTO_RESTART:-false}"

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run 'gcloud config set project YOUR_PROJECT'." >&2
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=================================================================="
echo "Project: $PROJECT_ID"
echo "Region:  $REGION"
echo "Service: $SERVICE_NAME"
echo "Topic:   $TOPIC_NAME"
echo "SA:      $SA_EMAIL"
echo "Frames:  gs://${FRAMES_BUCKET}/${FRAMES_PATH}"
echo "=================================================================="

# --- Enable required APIs ---
echo ">>> Enabling APIs..."
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project="$PROJECT_ID"

# --- Pub/Sub topic ---
echo ">>> Ensuring Pub/Sub topic exists..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics create "$TOPIC_NAME" --project="$PROJECT_ID"
    echo "    created topic $TOPIC_NAME"
else
    echo "    topic $TOPIC_NAME exists"
fi

# --- Service account ---
echo ">>> Ensuring service account exists..."
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Formula E Simulator" \
        --project="$PROJECT_ID"
    echo "    created SA $SA_EMAIL"
else
    echo "    SA $SA_EMAIL exists"
fi

# --- IAM grants ---
echo ">>> Granting roles..."
# Pub/Sub publisher
gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/pubsub.publisher" \
    --project="$PROJECT_ID" >/dev/null

# Storage reader on the frames bucket
gcloud storage buckets add-iam-policy-binding "gs://${FRAMES_BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectViewer" >/dev/null || \
    echo "    WARN: couldn't grant storage.objectViewer on gs://${FRAMES_BUCKET} (probably cross-project; bucket owner must grant)"

# --- Deploy ---
echo ">>> Deploying Cloud Run service..."
gcloud run deploy "$SERVICE_NAME" \
    --source=. \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --min-instances=1 \
    --max-instances=1 \
    --cpu=1 \
    --memory=512Mi \
    --no-cpu-throttling \
    --concurrency=10 \
    --timeout=3600 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},PUBSUB_TOPIC=${TOPIC_NAME},FRAMES_BUCKET=${FRAMES_BUCKET},FRAMES_PATH=${FRAMES_PATH},REPLAY_SPEED_MULTIPLIER=${REPLAY_SPEED_MULTIPLIER},AUTO_RESTART=${AUTO_RESTART}"

URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')
echo ""
echo "=================================================================="
echo "Deployed!"
echo "URL:    $URL"
echo "Status: curl ${URL}/status"
echo "=================================================================="