Good Day

 

Thank you for meeting with us. Please find below the meeting notes from our DDH Geospatial API discussion.

Submit API Preview Generation Without Version ID
The team discussed the limitation where the Submit API requires a Version ID, blocking preview generation in draft mode, where a version may not yet exist. Robert agreed to update the API so that preview services can be generated using a draft flag instead of a Version ID, enabling draft‑level geospatial previews similar to DDH.

Embedded URL and Collection ID Handling for Preview
There was confusion around how to construct the collection ID and pass dataset/resource IDs for preview URLs. Robert clarified that the collection value is returned automatically via the status API when checking a job using the request ID, and this response provides all required URLs—including the embedded URL—whether the dataset is in draft or published state.

Approval, Reject, and Other Endpoint Failures
Multiple API endpoints, including approve, reject, revoke, submit, are failing with null asset IDs or internal server errors, despite previously functioning correctly. Robert confirmed these are server‑side issues and requested detailed endpoint failure logs so he can investigate and track them for resolution.

QA Automation Findings and Negative Test Cases
The QA team identified several negative cases where APIs return incorrect success responses—such as validate API showing 200 OK for invalid inputs—and systemic errors across workflows. The team agreed to consolidate all negative‑case findings and SSL/service‑layer errors into a shared tracker so Robert can review and address them.

Follow-up tasks:

Submit API Draft Mode Enhancement: Implement the ability to generate a geospatial service in draft mode without requiring a version ID and notify the team upon completion. (Robert Mansour)
Approval and Reject Endpoints Issue: Investigate and resolve the server-side errors causing the approval and reject endpoints to fail, and update the team on the findings. (Robert Mansour)
Platform Endpoint Failures: Review and address the failures in other platform endpoints as documented in the shared Excel spreadsheet, and provide feedback to the team. (Robert Mansour)
Validation API Incorrect Status Code: Update the validate API to return appropriate error status codes (not 200) for invalid file names or vector requests. (Robert Mansour)
Service Layer API SSL Error: Investigate and resolve the SSL connection errors preventing access to the service layer APIs. (Robert Mansour)
Consolidation of QA Findings: Add all QA automation script findings, including negative test cases and observations, into the shared spreadsheet for Robert Mansour's review and action. (Megha, Jaganathan)
 

Once the above follow up task completed, Please let us know.

Thanks,
Karthikeyan K