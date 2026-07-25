# Gaia Spring Client Example

This example calls Gaia through the language-neutral HTTP contract. It does not embed the
Python Runtime or duplicate workflow rules in Java.

```java
var gaia = new GaiaClient("http://localhost:8000", "gaia-dev-key");
var run = gaia.createRun("inspect res-001", "java-user", "org-alpha", List.of("reader"));
```

Generate a typed client from `specs/openapi.json` when a customer project needs stronger
compile-time models. The P0 example intentionally keeps the integration surface small.
