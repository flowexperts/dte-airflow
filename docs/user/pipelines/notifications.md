# Notifications

A pipeline can notify people when its runs fail, retry or succeed. Notifications belong to
the pipeline, not its schedule, so manual runs and scheduled runs both send them.

## Adding one

On the pipeline page, open **Notifications ▸ Add notification**:

![New notification form](../assets/pipelines/notify-form.png)

1. **Notifier**: any notifier offered by an Airflow provider installed in your deployment.
   The stock image has Slack, Slack webhook, SMTP email, Amazon SES, SNS, SQS and Chime, and
   Microsoft Graph. The list comes from Airflow, so installing a provider package (Discord,
   PagerDuty, Opsgenie, Apprise, …) adds its notifiers with no DTE change.
2. **When**: any of *Failure*, *Retry*, *Success*. *Failure* fires once, after the last
   retry has failed.
3. **Parameters**: the notifier's own arguments, as JSON. Picking a notifier prefills its
   required ones, and sets its message argument (`text`, `message`, `html_content`, …) to
   `{{ dte_message }}`.

Most notifiers take an Airflow connection id (`slack_conn_id`, `smtp_conn_id`, …). Create
the connection in Airflow under **Admin ▸ Connections** first.

The saved notification shows in the panel with the events it fires on:

![Notifications panel](../assets/pipelines/notify-panel.png)

### Email

Create an **SMTP** connection (`team_email` here) with your mail server's host, port, login
and password, then pick **SmtpNotifier**:

```json
{
  "to": "data-team@example.com",
  "smtp_conn_id": "team_email",
  "from_email": "dte@example.com",
  "subject": "DTE orders_clean: {{ dte_event }}",
  "html_content": "<pre>{{ dte_message }}</pre>"
}
```

A failed run sends the pipeline, its DAG, the run and the error:

![Failure email](../assets/pipelines/notify-email.png)

### Slack

Create a **Slack Incoming Webhook** connection (`ops_slack`) with the webhook URL as its
password, then pick **SlackWebhookNotifier**:

```json
{ "slack_webhook_conn_id": "ops_slack", "text": "{{ dte_message }}" }
```

With a Slack app token instead, use a **Slack API** connection and **SlackNotifier**, which
also takes a `channel`.

Arguments the notifier templates can use these values:

| Value | Contains |
|---|---|
| `{{ dte_message }}` | the pipeline, its DAG, the run id and, on failure or retry, the error |
| `{{ dte_event }}` | `failure`, `retry` or `success` |

Airflow's usual template context (`{{ run_id }}`, `{{ dag.dag_id }}`, …) works too.

## Checked when you save

DTE refuses a notification, naming the problem, when:
- the notifier isn't one an installed provider registers,
- the parameters don't fit its arguments (a required one missing, an unknown one given), or
- a `*_conn_id` parameter names an Airflow connection that doesn't exist.

Whether the message actually arrives (a valid token, a channel the bot can post to) is only
known when it sends. A notification that fails to send is logged in the task log and never
changes the run's own outcome.

## API

```
GET /dte/api/notifiers                          installed notifiers and their arguments
GET /dte/api/pipelines/{id}/notifications       the pipeline's notifications
PUT /dte/api/pipelines/{id}/notifications       replace them: [{notifier, params, on}]
```

Notifications are also the `notifications` field of the pipeline; a pipeline `PUT` that omits
it keeps the current ones. Every change is a pipeline revision.
