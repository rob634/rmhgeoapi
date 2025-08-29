this file is created 28 August 2025 1800 DC time
This project had gotten very large and I am now rebuilding the core framework architecture which handles sequential and parallel operations and indempotency for serverless implementation and scaling
I want to depracate ALL controllers and start new with an abstract base class base controller that has our sequencing, task fan out, and completion patterns

Please add depracation warning at the top of all relevant python files

Architecture

controller service repository design

everything beigns with HTTP triggered function submit_job creates a message in the job queue and a record in the job table with status "queued". These have a unique jobId made from the hash of parameters. 

Queue triggered job function spins up and marks the record as "processing" and creates one or more tasks in the form of record(s) in the task table (with "queued" status) and message(s) in the tasks queue

Queue triggered task function spins up and marks corresponding task record as "processing" and completes task according to parameters. When tasks complete they update their status to "completed" (or "failed")

Last task "turns out the lights" by marking the job record stage completed and if it's the last stage it marks the job record status as completed

high level abstractions

Each Job ("job") contains at least 1 orchestration stage ("stage") which by nature is sequential and cannot be parallelized
Each job orchestration stage contains at least 1 task ("task"), tasks by nature can be completed in parallel, fully leveraging Azure Function App design
Each task checks if all other tasks are completed before terminating and updates their corresponding record in the task table. if it is the last task, it updates the job record to mark the stage as completed and if it's the final stage it marks the job itself as completed. If it is not the final stage it updates the stage status in the job record and creates a new message in the job queue with the same jobID for the next stage.

Abstraction models

Controller - has a job_type, defined stages (or just one), and defined tasks (or just one). This is created by the queue trigger job function. The HTTP trigger creates the job record with it's jobId (a parameter hash)

Job - This is essentially an instance of the relevant controller- it has a job_type, a processing stage (which is an ordinal value from the Controller of which it is a part), child task(s), and a status. Job should have a complete_job component that is triggered by the last stage completing succesfully. Complete_job will close out the process by updating all the relevant tables and EVENTUALLY triggering an external webhook (but not for now)

Stage - sequential operation forming part of a job chain. Has a prerequisite (unless it's stage 1) and a successor (unless it's stage n of n in which case it creates the job completion queue message)

*IMPORTANT* stages can be executed as individual jobs. For example, if a two part job has a sequence of "validate_data" and "process_data" we will likely have instances where we want to have a single sequence "validate_data" job. 

Task - this is a parallelizable operation created by a Job Stage. For example, "Validate_data" might spin up tasks to validate subsets of a data input in parallel and then "process_Data" might spin up tasks to process chunks in parallel. Two parallelizable stages of one job.

Status - Job or task status, has to be "queued", "processing", "completed" or "failed"

First controller to build: Hello Worlds, Worlds Reply

Stage 1:
Hello World job stage creates n "hello from <task_id>!" task messages with other relevant parameters and marks the job record stage as stage 1 or its name "Hello worlds"

Queue triggered tasks spin up and simply marks those hello tasks as complete. The first task marks the job record status as "processing" from "queued" and the last one changes the job record stage to stage 2 or its name "Worlds Reply" AND creates the stage 2 initiator message in the job queue with the list of task_id's to respond to.

Stage 2:
Queue triggered job spins back up, reads job status and stage and parameters, and again creates task messages with a "hello <task_id from stage 1> from <current task_id>" 
Queue triggered tasks spin back up and again first task marks job record as "processing" from "queued" and the last task, because it is stage n of n, creates a job completion message in the job queue

Completion Stage:
Queue triggered job spins up, aggregates tasks and conslidates messages and other relevant information into a job_result_data object which is put into the job record which is also marked as complete.

This pattern can provide the basis for complex geospatial ETL operations with sequential, parallelizable operations



