# Testing Numa FSM Pub/Sub by hand

> The automated suite lives in `tests/`; run it with `--test-tags=/numa_fsm_pubsub`. This
> walkthrough is still worth doing once, because it is the only way to see the
> **asynchronous delivery actually happen**: a test transaction never commits, so the
> worker never runs, and the suite therefore asserts the routing and the arrival
> separately.

## What it proves

That publishing from one FSM instance ends up as a chatter message on another one, having
travelled through a topic, a subscription and a background job — with nothing in the
publisher's code naming the subscriber.

## Before starting

- `numa_fsm_pubsub` installed, which brings `numa_fsm` and `numa_asynch_exec`.
- The asynchronous worker running. Without it the jobs pile up in the queue and nothing
  arrives; that is the single most common reason for "it does not work".

## Steps

### 1. Two FSM instances

Create two instances of any definition — **Settings → Technical → FSM Instances**, or from
whatever model drives them in your database. Call them the publisher and the subscriber.
Note the subscriber's id; you will look at its chatter.

### 2. A subscription

**Settings → Technical → FSM Subscriptions → New**:

| Field | Value |
|---|---|
| Topic | `system_ping` |
| Subscriber FSM Instance | the subscriber |
| Active | yes |

The topic `system_ping` ships with the module.

### 3. Publish

Open the **publisher**, and use the server action **Send a diagnostic ping to
subscribers** from the cog menu. It calls `record.publish('system_ping', payload)` with
the publisher's own name and the current time, and logs how many subscribers it was
handed to.

### 4. Look at the subscriber

Open the subscriber and read its chatter. A **PONG** message should appear, naming the
publisher and carrying the payload.

It does not appear instantly: the publication enqueued a job, and the message appears when
the worker picks it up. Refreshing after a few seconds is part of the test — if it were
immediate, the delivery would not be asynchronous, which is the point.

## What to check when it does not arrive

| Symptom | Where to look |
|---|---|
| The server action is not in the menu | The action is bound to `fsm.instance`; you are probably on another model. |
| The publisher logs "0 subscriber(s)" | The subscription is inactive, points at another instance, or at another topic. |
| The publisher logs a number, nothing arrives | The worker is not running, or the job failed: look at the job queue and the log. |
| The message arrives instantly | You are calling `notify()` directly instead of `publish()`. That is the worker's entry point, not the publisher's. |
| The handler raises | It is logged and swallowed on purpose: one subscriber breaking must not take down the publisher's job or the other subscribers. The traceback is in the log. |

## Variations worth trying

- **Several subscribers.** Add a second subscription to the same topic: the publisher
  reports two, and both chatters get a PONG. Each gets its own job.
- **An inactive subscription.** Untick Active: the publisher reports one fewer.
- **A topic nobody declared.** `record.publish('whatever', {})` returns 0 and logs it. It
  is not an error — the transport does not validate — but with nothing declared there is
  nobody subscribed either.
- **A payload with nested structures.** It travels as JSON; the handler prints it back
  into the chatter.
- **No handler.** Subscribe to a topic with no `_handle_topic_<topic>` method: the
  delivery becomes an FSM event named after the topic, which is what unifies messages
  from the network with events raised inside the machine. The instance has to be running
  or paused for that to do anything.
