#!/bin/bash
# =============================================================================
# Deploy Script for Geospatial API (4-App Architecture)
# =============================================================================
# Usage: ./deploy.sh [orchestrator|gateway|docker|dagbrain|all]
# Default: orchestrator only
#
# TARGETS (named by APP_MODE role):
#   orchestrator - rmhazuregeoapi (Function App, APP_MODE=standalone)
#   gateway      - rmhgeogateway (Function App, APP_MODE=platform)
#   docker       - rmhheavyapi (Docker, APP_MODE=worker_docker)
#   dagbrain     - rmhdagmaster (Docker, APP_MODE=orchestrator)
#   all          - Deploy all 4 apps (Function Apps first, then Docker)
#
# Docker apps share the same image (geospatial-worker:VERSION).
# When deploying both, the image is built once and pushed to both apps.
#
# LAST UPDATED: 18 MAR 2026
# =============================================================================

set -e

# App Names
ORCHESTRATOR_APP="rmhazuregeoapi"
GATEWAY_APP="rmhgeogateway"
DOCKER_APP="rmhheavyapi"
DAGBRAIN_APP="rmhdagmaster"

# Common Config
RESOURCE_GROUP="rmhazure_rg"
ACR_REGISTRY="rmhazureacr"
ACR_REPO="geospatial-worker"

# URLs
ORCHESTRATOR_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
GATEWAY_URL="https://rmhgeogateway-gdc4hrafawfrcqak.eastus-01.azurewebsites.net"
DOCKER_URL="https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net"
DAGBRAIN_URL="https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net"

# Get version from config/__init__.py
VERSION=$(grep -o '__version__ = "[^"]*"' config/__init__.py | cut -d'"' -f2)

echo "================================================"
echo "Geospatial API Deployment"
echo "Version: $VERSION"
echo "================================================"
echo ""

# Determine deployment target (default: orchestrator)
TARGET=${1:-orchestrator}

# Track whether Docker image has been built this run
DOCKER_IMAGE_BUILT=false

# -----------------------------------------------------------------------------
# Deploy a Function App (generic helper)
# Usage: deploy_functionapp APP_NAME APP_URL DISPLAY_NAME
# -----------------------------------------------------------------------------
deploy_functionapp() {
    local APP_NAME=$1
    local APP_URL=$2
    local DISPLAY_NAME=$3

    echo "📦 Deploying $DISPLAY_NAME ($APP_NAME)..."
    echo ""

    func azure functionapp publish $APP_NAME --python --build remote

    echo ""
    echo "⏳ Waiting for app to restart (45 seconds)..."
    sleep 45

    echo ""
    echo "🔍 Verifying deployment..."

    # Health check
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL/api/health")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "✅ Health check passed (HTTP $HTTP_STATUS)"
    else
        echo "❌ Health check failed (HTTP $HTTP_STATUS)"
        echo "   Check Application Insights for startup errors"
        exit 1
    fi

    # Version check
    DEPLOYED_VERSION=$(curl -s "$APP_URL/api/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "unknown")
    echo "📋 Deployed version: $DEPLOYED_VERSION"

    if [ "$DEPLOYED_VERSION" = "$VERSION" ]; then
        echo "✅ Version matches expected ($VERSION)"
    else
        echo "⚠️  Version mismatch: expected $VERSION, got $DEPLOYED_VERSION"
    fi

    echo ""
    echo "🎉 $DISPLAY_NAME deployment complete!"
}

# -----------------------------------------------------------------------------
# Build Docker image in ACR (only if not already built this run)
# -----------------------------------------------------------------------------
build_docker_image() {
    if [ "$DOCKER_IMAGE_BUILT" = true ]; then
        echo "📦 Docker image already built this run — skipping rebuild"
        return 0
    fi

    echo "📦 Building Docker image ($ACR_REPO:$VERSION) in ACR..."
    set +e
    az acr build --registry $ACR_REGISTRY --image $ACR_REPO:$VERSION --file Dockerfile .
    ACR_EXIT=$?
    set -e

    if [ $ACR_EXIT -ne 0 ]; then
        echo ""
        echo "=============================================="
        echo "❌ ACR BUILD FAILED (exit code: $ACR_EXIT)"
        echo "=============================================="
        exit 1
    fi

    DOCKER_IMAGE_BUILT=true
}

# -----------------------------------------------------------------------------
# Deploy a Docker app (generic helper)
# Usage: deploy_docker_app APP_NAME APP_URL DISPLAY_NAME
# -----------------------------------------------------------------------------
deploy_docker_app() {
    local APP_NAME=$1
    local APP_URL=$2
    local DISPLAY_NAME=$3

    echo "🐳 Deploying $DISPLAY_NAME ($APP_NAME)..."
    echo ""

    # Build image if needed
    build_docker_image

    # Update container
    echo ""
    echo "🔄 Updating container configuration..."
    az webapp config container set \
        --name $APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --container-image-name "$ACR_REGISTRY.azurecr.io/$ACR_REPO:$VERSION"

    # Restart
    echo ""
    echo "🔄 Restarting $DISPLAY_NAME..."
    az webapp stop --name $APP_NAME --resource-group $RESOURCE_GROUP
    az webapp start --name $APP_NAME --resource-group $RESOURCE_GROUP

    echo ""
    echo "⏳ Waiting for container to start (60 seconds)..."
    sleep 60

    echo ""
    echo "🔍 Verifying deployment..."

    # Health check (Docker apps use /health not /api/health)
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL/health")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "✅ Health check passed (HTTP $HTTP_STATUS)"
    elif [ "$HTTP_STATUS" = "503" ]; then
        echo "⚠️  Health check returned 503 (degraded — check /health for details)"
    else
        echo "❌ Health check failed (HTTP $HTTP_STATUS)"
        echo "   Check container logs: az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP"
        exit 1
    fi

    echo ""
    echo "🎉 $DISPLAY_NAME deployment complete!"
}

deploy_orchestrator() {
    deploy_functionapp "$ORCHESTRATOR_APP" "$ORCHESTRATOR_URL" "Orchestrator"
}

deploy_gateway() {
    deploy_functionapp "$GATEWAY_APP" "$GATEWAY_URL" "Gateway"
}

deploy_docker() {
    deploy_docker_app "$DOCKER_APP" "$DOCKER_URL" "Docker Worker"
}

deploy_dagbrain() {
    deploy_docker_app "$DAGBRAIN_APP" "$DAGBRAIN_URL" "DAG Brain"
}

case $TARGET in
    orchestrator)
        deploy_orchestrator
        ;;
    gateway)
        deploy_gateway
        ;;
    docker)
        deploy_docker
        ;;
    dagbrain)
        deploy_dagbrain
        ;;
    all)
        deploy_orchestrator
        echo ""
        echo "------------------------------------------------"
        echo ""
        deploy_gateway
        echo ""
        echo "------------------------------------------------"
        echo ""
        deploy_docker
        echo ""
        echo "------------------------------------------------"
        echo ""
        deploy_dagbrain
        ;;
    *)
        echo "Usage: ./deploy.sh [orchestrator|gateway|docker|dagbrain|all]"
        echo ""
        echo "  orchestrator - Deploy Orchestrator Function App (rmhazuregeoapi)"
        echo "  gateway      - Deploy Gateway Function App (rmhgeogateway)"
        echo "  docker       - Deploy Docker Worker (rmhheavyapi, APP_MODE=worker_docker)"
        echo "  dagbrain     - Deploy DAG Brain (rmhdagmaster, APP_MODE=orchestrator)"
        echo "  all          - Deploy all 4 apps"
        exit 1
        ;;
esac

echo ""
echo "================================================"
echo "Deployment Summary"
echo "================================================"
echo "Version: $VERSION"
echo "Target:  $TARGET"
echo "Status:  Complete"
echo "================================================"
