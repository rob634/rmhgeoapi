#!/bin/bash
# =============================================================================
# Deploy Script for Geospatial API (3-App Architecture)
# =============================================================================
# Usage: ./deploy.sh [orchestrator|gateway|docker|all]
# Default: orchestrator only
#
# TARGETS (named by APP_MODE role):
#   orchestrator - rmhazuregeoapi (APP_MODE=standalone, job orchestration)
#   gateway      - rmhgeogateway (APP_MODE=platform, B2B API gateway)
#   docker       - rmhheavyapi (APP_MODE=worker_docker, heavy processing)
#   all          - Deploy all 3 apps
#
# LAST UPDATED: 07 FEB 2026
# =============================================================================

set -e

# App Names
ORCHESTRATOR_APP="rmhazuregeoapi"
GATEWAY_APP="rmhgeogateway"
DOCKER_APP="rmhheavyapi"

# Common Config
RESOURCE_GROUP="rmhazure_rg"
ACR_REGISTRY="rmhazureacr"
ACR_REPO="geospatial-worker"

# URLs
ORCHESTRATOR_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
GATEWAY_URL="https://rmhgeogateway-gdc4hrafawfrcqak.eastus-01.azurewebsites.net"
DOCKER_URL="https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net"

# Get version from config/__init__.py
VERSION=$(grep -o '__version__ = "[^"]*"' config/__init__.py | cut -d'"' -f2)

echo "================================================"
echo "Geospatial API Deployment"
echo "Version: $VERSION"
echo "================================================"
echo ""

# Determine deployment target (default: orchestrator)
TARGET=${1:-orchestrator}

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

deploy_orchestrator() {
    deploy_functionapp "$ORCHESTRATOR_APP" "$ORCHESTRATOR_URL" "Orchestrator"
}

deploy_gateway() {
    deploy_functionapp "$GATEWAY_APP" "$GATEWAY_URL" "Gateway"
}

deploy_docker() {
    echo "🐳 Building and deploying Docker Worker ($DOCKER_APP)..."
    echo ""

    # Build and push to ACR (runs server-side, we just wait for completion)
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
        echo "   To retry Docker only:  ./deploy.sh docker"
        echo "=============================================="
        exit 1
    fi

    # Update container
    echo ""
    echo "🔄 Updating container configuration..."
    az webapp config container set \
        --name $DOCKER_APP \
        --resource-group $RESOURCE_GROUP \
        --container-image-name "$ACR_REGISTRY.azurecr.io/$ACR_REPO:$VERSION"

    # Restart
    echo ""
    echo "🔄 Restarting Docker Worker..."
    az webapp stop --name $DOCKER_APP --resource-group $RESOURCE_GROUP
    az webapp start --name $DOCKER_APP --resource-group $RESOURCE_GROUP

    echo ""
    echo "⏳ Waiting for container to start (60 seconds)..."
    sleep 60

    echo ""
    echo "🔍 Verifying deployment..."

    # Health check
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$DOCKER_URL/health")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "✅ Health check passed (HTTP $HTTP_STATUS)"
    else
        echo "❌ Health check failed (HTTP $HTTP_STATUS)"
        echo "   Check container logs: az webapp log tail --name $DOCKER_APP --resource-group $RESOURCE_GROUP"
        exit 1
    fi

    echo ""
    echo "🎉 Docker Worker deployment complete!"
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
        ;;
    *)
        echo "Usage: ./deploy.sh [orchestrator|gateway|docker|all]"
        echo ""
        echo "  orchestrator - Deploy Orchestrator (rmhazuregeoapi, APP_MODE=standalone)"
        echo "  gateway      - Deploy Gateway (rmhgeogateway, APP_MODE=platform)"
        echo "  docker       - Deploy Docker Worker (rmhheavyapi, APP_MODE=worker_docker)"
        echo "  all          - Deploy all 3 apps"
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
