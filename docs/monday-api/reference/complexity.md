---
updatedAt: 2026-03-05T20:02:38.000Z
---

Fetch the complete documentation index at: https://developer.monday.com/api-reference/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Complexity

Learn how to query the complexity of an API call using the monday.com platform API

Query complexity defines the cost of each operation you make. Each API token is allotted a fixed [complexity limit](https://developer.monday.com/api-reference/docs/rate-limits) for a given period to help manage the load placed on the API.

# Queries

## Get complexity

* Returns a JSON object containing the complexity cost of your queries
* Can be included in any API request to return the cost of that specific query or mutation.

```graphql GraphQL
query {
  complexity {
    before
    query
    after
    reset_in_x_seconds
  }
  boards (ids: 1234567890) {
    items {
      id
      name
    }
  }
}
```

### Fields

| Field                 | Type   | Description                                                          |
| :-------------------- | :----- | :------------------------------------------------------------------- |
| after                 | `Int!` | The remaining complexity after the query's execution.                |
| before                | `Int!` | The remaining complexity before the query's execution.               |
| query                 | `Int!` | This specific query's complexity.                                    |
| reset\_in\_x\_seconds | `Int!` | The length of time (in seconds) before the complexity budget resets. |