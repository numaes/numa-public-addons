Description
===========

This module executes periodic service in an easy to maintain strategy.

A service could in operational state and then it runs periodically according
the programmed interval period.

A service could be configured, tested or put into maintenance state. In this
states no programmed execution occurs, and thus could be easyly controlled by
the operator.

Every time an execution occurs, it is logged on the standard log.
If an exception occurs, the transaction will be rolled back at the next available
step.

You can set up the service so it will move to maintenance state automatically
if an exception occurs. If not, the run will be retried for ever til a no exception
execution.

The basic service dispatch occurs at a period of 10 minutes. All services will be
checked to run the ones wich its next run is already happened.




