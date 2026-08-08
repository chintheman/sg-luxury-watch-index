---
name: qa-authz
description: Personas, credential fixtures, the authz matrix format and expected status classes. Load when building or extending .qa/authz-matrix.yaml.
---

# Authorization testing

Schema fuzzing cannot test authorization: Schemathesis has no idea who *should*
see what. The matrix is the only thing here that covers IDOR, tenant leakage and
privilege escalation.

## Personas

| Persona | Credential fixture | Represents |
|---|---|---|
| `anonymous` | none | unauthenticated traffic |
| `user_a` | `<<fixture>>` | ordinary owner of resource A |
| `user_b` | `<<fixture>>` | ordinary user who owns nothing of A's — **the IDOR probe** |
| `admin` | `<<fixture>>` | elevated |
| `expired` | `<<fixture>>` | valid-shaped but expired session |
| `wrong_tenant` | `<<fixture>>` | valid user in another tenant — **the leakage probe** |

`user_b` and `wrong_tenant` are the rows that find real bugs. A matrix without
them tests authentication, not authorization.

## Matrix format

```yaml
version: 1
routes:
  - route: "GET /api/carts/{id}"
    owner_param: id
    expect:
      anonymous:    401
      user_a:       200      # owns it
      user_b:       404      # must NOT be 403 — see below
      admin:        200
      expired:      401
      wrong_tenant: 404
```

## 403 versus 404 is a real finding

Returning **403** for a resource the caller may not see confirms it exists.
Returning **404** hides existence. Which is correct depends on the product, but
it must be *decided* and consistent — an endpoint that 403s where its siblings
404 is an information leak, and it is exactly the kind of inconsistency this
matrix surfaces.

State the intended convention here on install: `<<403 | 404>>`.

## Never guess a cell

An unknown expectation is a question for a human, not a `200` you assumed to
silence G8. A wrong row is worse than a missing one, because it converts an open
question into a passing test that will be cited as evidence.

## G8

Every route must have a row. CI fails when a route is added without one. That
check is what keeps the matrix from decaying the moment nobody is looking.
