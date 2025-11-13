# Azure Service Bus RBAC Roles - CoreMachine Requirements

**Date**: 5 NOV 2025
**Author**: Robert Harrison
**Purpose**: Clarify Service Bus RBAC role requirements for Azure Functions
**Context**: Function App needs to send AND receive messages from Service Bus queues

---

## 🎯 Quick Answer

**YES, you need BOTH roles OR use "Azure Service Bus Data Owner"**

### Current Production Configuration (Working)
```
Function App: rmhazuregeoapi
Managed Identity Principal ID: 995badc6-9b03-481f-9544-9f5957dd893d
Service Bus Namespace: rmhazure.servicebus.windows.net

✅ CURRENT ROLE: Azure Service Bus Data Owner
```

**This single role provides full send + receive permissions!**

---

## 📊 Service Bus RBAC Roles Comparison

### Option 1: Azure Service Bus Data Owner (RECOMMENDED - What You Have)

**Permissions**: Full access (send + receive + manage)
```json
{
  "role": "Azure Service Bus Data Owner",
  "actions": [
    "Microsoft.ServiceBus/*"
  ],
  "description": "Allows for full access to Azure Service Bus resources"
}
```

**Use Case**:
- ✅ Function Apps that need to SEND and RECEIVE messages
- ✅ CoreMachine (sends jobs to queue, receives tasks from queue)
- ✅ Simplest configuration (one role covers everything)

**Assignment Command**:
```bash
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Owner" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>
```

---

### Option 2: Azure Service Bus Data Sender + Data Receiver (Alternative)

**If you want to follow principle of least privilege**, you can assign BOTH roles:

#### Azure Service Bus Data Sender
```json
{
  "role": "Azure Service Bus Data Sender",
  "actions": [
    "Microsoft.ServiceBus/*/queues/read",
    "Microsoft.ServiceBus/*/topics/read",
    "Microsoft.ServiceBus/*/topics/subscriptions/read"
  ],
  "description": "Allows for send access to Azure Service Bus resources"
}
```

**Permissions**: Send messages to queues/topics

#### Azure Service Bus Data Receiver
```json
{
  "role": "Azure Service Bus Data Receiver",
  "actions": [
    "Microsoft.ServiceBus/*/queues/read",
    "Microsoft.ServiceBus/*/topics/read",
    "Microsoft.ServiceBus/*/topics/subscriptions/read"
  ],
  "description": "Allows for receive access to Azure Service Bus resources"
}
```

**Permissions**: Receive messages from queues/topics

**Assignment Commands** (if using separate roles):
```bash
# Sender role
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Sender" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>

# Receiver role
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Receiver" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>
```

---

## 🔍 CoreMachine Service Bus Usage Patterns

### Why CoreMachine Needs BOTH Send + Receive

```
┌──────────────────────────────────────────────────────────────┐
│  HTTP Trigger (trigger_job_submit.py)                       │
│  - Receives HTTP POST /api/jobs/submit/{job_type}           │
│  - Creates job in PostgreSQL                                │
│  - SENDS message to "geospatial-jobs" queue                 │  ← Needs SENDER
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Service Bus Queue: geospatial-jobs                          │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Service Bus Trigger (trigger_job_processor.py)              │
│  - RECEIVES message from "geospatial-jobs" queue            │  ← Needs RECEIVER
│  - Loads job from PostgreSQL                                │
│  - Executes job controller                                  │
│  - SENDS N task messages to "geospatial-tasks" queue        │  ← Needs SENDER
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Service Bus Queue: geospatial-tasks                         │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Service Bus Trigger (trigger_task_processor.py)             │
│  - RECEIVES message from "geospatial-tasks" queue           │  ← Needs RECEIVER
│  - Loads task from PostgreSQL                               │
│  - Executes task handler                                    │
│  - Updates task status                                      │
│  - (Last task) SENDS stage advancement message             │  ← Needs SENDER
└──────────────────────────────────────────────────────────────┘
```

**Summary**: Function App needs to:
1. **SEND** messages when submitting jobs
2. **RECEIVE** messages from job queue
3. **SEND** messages when creating tasks
4. **RECEIVE** messages from task queue
5. **SEND** messages for stage advancement

---

## ✅ Recommendation for Corporate Deployment

### For Development/Testing: Use "Azure Service Bus Data Owner"
- **Pros**:
  - Single role assignment (simpler)
  - Covers all scenarios
  - Matches current production config
  - Easier to troubleshoot
- **Cons**:
  - More permissions than strictly needed
  - Not following principle of least privilege

### For Production: Consider "Data Sender + Data Receiver"
- **Pros**:
  - Principle of least privilege
  - Better security posture
  - Audit trail shows explicit permissions
- **Cons**:
  - Two role assignments to manage
  - Slightly more complex setup

---

## 🔧 Verification Commands

### Check Current Role Assignments
```bash
# Get Function App managed identity principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --resource-group <resource-group> \
  --name <function-app-name> \
  --query principalId -o tsv)

echo "Function App Principal ID: $PRINCIPAL_ID"

# Check Service Bus role assignments
az role assignment list \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace> \
  --query "[?principalId=='$PRINCIPAL_ID'].{role:roleDefinitionName}" -o table
```

### Test Send Permissions
```bash
# Try to send a message (requires Sender or Owner role)
az servicebus queue send-message \
  --resource-group <resource-group> \
  --namespace-name <namespace> \
  --name geospatial-jobs \
  --message "test message"
```

### Test Receive Permissions
```bash
# Try to receive a message (requires Receiver or Owner role)
az servicebus queue receive-message \
  --resource-group <resource-group> \
  --namespace-name <namespace> \
  --name geospatial-jobs \
  --max-count 1
```

---

## 📋 Configuration in Function App

### Connection String Format (Managed Identity)

**App Settings** (what you need in Function App configuration):
```bash
ServiceBusConnection__fullyQualifiedNamespace=<namespace>.servicebus.windows.net
ServiceBusConnection__credential=managedidentity
```

**NOT** using connection string with secrets:
```bash
# ❌ DON'T USE (legacy pattern)
ServiceBusConnection=Endpoint=sb://<namespace>.servicebus.windows.net/;SharedAccessKeyName=...;SharedAccessKey=...
```

---

## 🚨 Common Issues

### Issue 1: "Unauthorized" errors when sending messages
**Cause**: Missing "Azure Service Bus Data Sender" or "Data Owner" role
**Fix**: Assign appropriate role to Function App managed identity

### Issue 2: "Unauthorized" errors when receiving messages
**Cause**: Missing "Azure Service Bus Data Receiver" or "Data Owner" role
**Fix**: Assign appropriate role to Function App managed identity

### Issue 3: Function App can send but not receive (or vice versa)
**Cause**: Only one role assigned (Sender OR Receiver)
**Fix**: Either assign BOTH roles OR switch to "Data Owner" role

### Issue 4: Role assignment exists but still getting errors
**Cause**: Role propagation delay (can take 5-10 minutes)
**Fix**: Wait 10 minutes after role assignment before testing

---

## 📊 Corporate Deployment Decision Matrix

| Scenario | Recommended Role(s) | Rationale |
|----------|---------------------|-----------|
| **Development/Testing** | Azure Service Bus Data Owner | Simplicity, matches current working config |
| **Production (Standard security)** | Azure Service Bus Data Owner | Operational simplicity, standard practice |
| **Production (High security/compliance)** | Data Sender + Data Receiver | Principle of least privilege, explicit permissions |
| **Multi-tenant environments** | Data Sender + Data Receiver | Clear permission boundaries per service |
| **Troubleshooting/debugging** | Data Owner | Full diagnostic capabilities |

---

## 🔐 Security Considerations

### Azure Service Bus Data Owner
- **Security Impact**: Moderate
- **Permissions**: Can send, receive, manage queues/topics
- **Risk**: Managed identity could potentially create/delete queues
- **Mitigation**: Azure Function code doesn't have management SDK, only messaging SDK

### Data Sender + Data Receiver
- **Security Impact**: Low
- **Permissions**: Can only send/receive messages, cannot manage resources
- **Risk**: Minimal - can only read/write messages
- **Mitigation**: Already implements principle of least privilege

### Connection String with Shared Access Keys
- **Security Impact**: High
- **Permissions**: Full access based on key type (RootManageSharedAccessKey)
- **Risk**: Key compromise = full Service Bus access
- **Mitigation**: ❌ DON'T USE - Use managed identity instead!

---

## 📝 Corporate IT Request Template

**For your corporate deployment**, request the following:

```
Service Bus RBAC Configuration Request
---------------------------------------

Resource: Azure Service Bus Namespace
Name: <corporate-namespace-name>
Resource Group: <corporate-resource-group>

Identity to Grant Access:
- Type: System-Assigned Managed Identity
- Resource: Azure Function App (will be created)
- Resource Name: <corporate-function-app-name>

Role Assignment Requested:
Option 1 (Recommended for simplicity):
  - Role: Azure Service Bus Data Owner
  - Scope: Service Bus Namespace level

Option 2 (Higher security posture):
  - Role 1: Azure Service Bus Data Sender
  - Role 2: Azure Service Bus Data Receiver
  - Scope: Service Bus Namespace level (both roles)

Justification:
- Function App needs to send job messages to Service Bus queues
- Function App needs to receive task messages from Service Bus queues
- This enables asynchronous job processing architecture
- Managed Identity provides passwordless authentication (no secrets)

Alternative (If managed identity not approved):
- Provide Service Bus connection string with Send+Listen permissions
- WARNING: Connection strings are less secure than managed identity
```

---

## ✅ Summary

**Current Production Configuration** (Working):
- Role: **Azure Service Bus Data Owner**
- Principal: rmhazuregeoapi Function App
- Scope: rmhazure Service Bus Namespace

**For Corporate Deployment**:
- **Development**: Use "Azure Service Bus Data Owner" (simplest)
- **Production**: Either role works, choose based on security requirements

**Key Takeaway**:
- "Data Owner" = One role that covers everything ✅
- "Data Sender + Data Receiver" = Two roles for least privilege ✅
- Both options work perfectly for CoreMachine!

---

**Document Status**: Ready for Corporate IT Review
**Last Updated**: 5 NOV 2025
**Related Documents**:
- [CORPORATE_AZURE_CONFIG_REQUEST.md](CORPORATE_AZURE_CONFIG_REQUEST.md) - Full deployment guide
- [AZURE_CONFIG_QUICK_REFERENCE.md](AZURE_CONFIG_QUICK_REFERENCE.md) - Quick reference
