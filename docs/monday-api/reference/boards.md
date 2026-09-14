---
updatedAt: 2026-05-24T08:27:37.000Z
---

Fetch the complete documentation index at: https://developer.monday.com/api-reference/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Boards

Learn how to read, create, update, and delete boards using the platform API

monday.com [boards](https://support.monday.com/hc/en-us/articles/115005317249-The-Basics-of-a-Board) are where users input all of their data, making them a core component of the platform. The board's structure consists of <Glossary>items</Glossary>(rows), [groups](https://support.monday.com/hc/en-us/articles/360011472320-The-basics-of-groups) (groups of rows), and [columns](https://support.monday.com/hc/en-us/articles/115005466609-The-basics-of-columns), and the board's data is stored in items and their respective [updates](https://support.monday.com/hc/en-us/articles/115005900249-The-Updates-Section) sections.

# Queries

## Get boards

* **Required scope: `boards:read`**
* Returns an array containing metadata about one or a collection of boards
* Can be queried directly at the root or nested within another query (e.g., `items`)

```graphql GraphQL
query {
  boards(
    ids: [1234567890]
    hierarchy_types: [classic, multi_level]
  ) {
    name
    state
    permissions
    items_page {
      items {
        id
        name
      }
    }
  }
}
```
```javascript JavaScript
import { ApiClient } from "@mondaydotcomorg/api";
const mondayApiClient = new ApiClient({ token: myToken});

const query = `query { boards (ids: [1234567890]) { name state permissions items_page { items { id name }}}}`
const response = await mondayApiClient.request(query);
```

### Arguments

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Argument
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum Values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        board_kind
      </td>

      <td>
        `BoardKind`
      </td>

      <td>
        The type of board to return.
      </td>

      <td>
        `private`  
        `public`  
        `share`
      </td>
    </tr>

    <tr>
      <td>
        hierarchy_type
      </td>

      <td>
        `[BoardHierarchy!]`
      </td>

      <td>
        The board hierarchy type to filter by. If omitted, only `classic` boards will be returned unless specific board IDs are provided.
      </td>

      <td>
        `classic`  
        `multi_level`
      </td>
    </tr>

    <tr>
      <td>
        ids
      </td>

      <td>
        `[ID!]`
      </td>

      <td>
        The specific board IDs to return.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        limit
      </td>

      <td>
        `Int`
      </td>

      <td>
        The number of boards to return. The default is 25.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        order_by
      </td>

      <td>
        `BoardsOrderBy`
      </td>

      <td>
        The order in which to retrieve your boards.
      </td>

      <td>
        `created_at` (desc.)  
        `used_at` (desc.)
      </td>
    </tr>

    <tr>
      <td>
        page
      </td>

      <td>
        `Int`
      </td>

      <td>
        The page number to return. Starts at 1.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        state
      </td>

      <td>
        `State`
      </td>

      <td>
        The state of the board to return. The default is `active`.
      </td>

      <td>
        `active`  
        `all`  
        `archived` `deleted`
      </td>
    </tr>

    <tr>
      <td>
        workspace_ids
      </td>

      <td>
        `[ID]`
      </td>

      <td>
        The specific workspace IDs that contain the boards to return.
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

### Fields

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Field
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum Values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        access_level
      </td>

      <td>
        `BoardAccessLevel!`
      </td>

      <td>
        The user's board permission level.
      </td>

      <td>
        `edit`  
        `view`
      </td>
    </tr>

    <tr>
      <td>
        activity_logs
      </td>

      <td>
        [`[ActivityLogType]`](https://developer.monday.com/api-reference/docs/activity-logs)
      </td>

      <td>
        The activity log events for the queried board(s).
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_folder_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The unique identifier of the folder that contains the board(s). Returns `null` if the board is not in a folder.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_kind
      </td>

      <td>
        `BoardKind!`
      </td>

      <td>
        The board's type.
      </td>

      <td>
        `private`  
        `public`  
        `share`
      </td>
    </tr>

    <tr>
      <td>
        columns
      </td>

      <td>
        [`[Column]`](https://developer.monday.com/api-reference/docs/columns)
      </td>

      <td>
        The board's visible columns.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        communication
      </td>

      <td>
        `JSON`
      </td>

      <td>
        The board's communication value (typically a meeting ID).
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        creator
      </td>

      <td>
        [`User!`](https://developer.monday.com/api-reference/reference/users#fields)
      </td>

      <td>
        The board's creator.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        description
      </td>

      <td>
        `String`
      </td>

      <td>
        The board's description.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        groups
      </td>

      <td>
        [`[Group]`](https://developer.monday.com/api-reference/reference/groups#fields)
      </td>

      <td>
        The board's visible groups.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        hierarchy_type
      </td>

      <td>
        `BoardHierarchy`
      </td>

      <td>
        The board's hierarchy type.
      </td>

      <td>
        `classic`  
        `multi_level`
      </td>
    </tr>

    <tr>
      <td>
        id
      </td>

      <td>
        `ID!`
      </td>

      <td>
        The board's unique identifier.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        item_terminology
      </td>

      <td>
        `String`
      </td>

      <td>
        The nickname for items on the board. Can be a predefined or custom value.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        items_count
      </td>

      <td>
        `Int`
      </td>

      <td>
        The number of items on the board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        items_page
      </td>

      <td>
        [`ItemsResponse!`](https://developer.monday.com/api-reference/docs/items_page)
      </td>

      <td>
        The board's items. Can be used to retrieve all items on a board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        name
      </td>

      <td>
        `String!`
      </td>

      <td>
        The board's name.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        object_type_unique_key
      </td>

      <td>
        `String`
      </td>

      <td>
        A unique identifier for the board's object type. May return `null` for boards without a specific object type classification.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        owner (DEPRECATED)
      </td>

      <td>
        [`User!` ](https://developer.monday.com/api-reference/reference/users#fields)
      </td>

      <td>
        The user who created the board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        owners
      </td>

      <td>
        [`[User]!`](https://developer.monday.com/api-reference/reference/users#fields)
      </td>

      <td>
        The board's owners.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        permissions
      </td>

      <td>
        `String!`
      </td>

      <td>
        The board's permissions.
      </td>

      <td>
        `assignee`  
        `collaborators`  
        `everyone`  
        `owners`
      </td>
    </tr>

    <tr>
      <td>
        state
      </td>

      <td>
        `State!`
      </td>

      <td>
        The board's state.
      </td>

      <td>
        `active`  
        `all`  
        `archived`  
        `deleted`
      </td>
    </tr>

    <tr>
      <td>
        subscribers
      </td>

      <td>
        [`[User]!`](https://developer.monday.com/api-reference/reference/users#fields)
      </td>

      <td>
        The board's subscribers.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        tags
      </td>

      <td>
        [`[Tag]`](https://developer.monday.com/api-reference/reference/tags-1#fields)
      </td>

      <td>
        The board's tags.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        team_owners
      </td>

      <td>
        [`[Team!]`](https://developer.monday.com/api-reference/reference/teams#fields)
      </td>

      <td>
        The board's team owners.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        team_subscribers
      </td>

      <td>
        [`[Team!]`](https://developer.monday.com/api-reference/reference/teams#fields)
      </td>

      <td>
        The board's team subscribers. A value of `-1` indicates that the "everyone at account" team is subscribed to this board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        top_group
      </td>

      <td>
        [`Group!`](https://developer.monday.com/api-reference/reference/groups#fields)
      </td>

      <td>
        The group at the top of the board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        type
      </td>

      <td>
        `BoardObjectType`
      </td>

      <td>
        The board's object type.
      </td>

      <td>
        `board`  
        `custom_object`  
        `document`  
        `sub_items_board`
      </td>
    </tr>

    <tr>
      <td>
        updated_at
      </td>

      <td>
        `ISO8601DateTime`
      </td>

      <td>
        The last time the board was updated.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        updates
      </td>

      <td>
        [`[Update]`](https://developer.monday.com/api-reference/docs/updates)
      </td>

      <td>
        The board's updates.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        url
      </td>

      <td>
        `String!`
      </td>

      <td>
        The board's URL.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        views
      </td>

      <td>
        `[BoardView]`
      </td>

      <td>
        The board's views.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        workspace
      </td>

      <td>
        [`Workspace`](https://developer.monday.com/api-reference/docs/workspaces)
      </td>

      <td>
        The workspace that contains the board. Returns `null` for the _Main_ workspace.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        workspace_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The unique identifier of the board's workspace. Returns `null` for the _Main_ workspace.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        created_from_board_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The unique identifier of the source board this board was created from (e.g., when duplicated). Returns `null` if the board was not created from another board. **Only available in versions `2026-04` and later.**
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        folder
      </td>

      <td>
        [`Folder`](https://developer.monday.com/api-reference/reference/folders)
      </td>

      <td>
        The folder containing this board. Returns `null` if the board is not in a folder. **Only available in versions `2026-04` and later.**
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        inferred_metadata
      </td>

      <td>
        [`BoardInferredMetadata`](https://developer.monday.com/api-reference/reference/boards-other-types#boardinferredmetadata)
      </td>

      <td>
        Inferred metadata for the board (for example, custom terminology for items). **Only available in versions `2026-07` and later.**
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        manual_metadata
      </td>

      <td>
        [`BoardManualMetadata`](https://developer.monday.com/api-reference/reference/boards-other-types#boardmanualmetadata)
      </td>

      <td>
        Manually set metadata for the board (for example, markdown describing the board). **Only available in versions `2026-07` and later.**
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

# Mutations

**Required scope: `boards:write`**

## Create board

Creates a new board. Returns [`Board`](https://developer.monday.com/api-reference/docs/boards#fields).

The user who creates the board is automatically added as a board owner when creating a private or shareable board or if `board_owners_ids` is not provided.

<Callout icon="🚧" theme="warn">
  This mutation has an additional rate limit of **40** mutations per minute.
</Callout>

```graphql GraphQL
mutation {
  create_board(
    board_name: "my board"
    board_kind: public
    item_nickname: { preset_type: "item" }
  ) { 
    id 
  }
}
```

### Arguments

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Argument
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum Values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        board_kind
      </td>

      <td>
        `BoardKind!`
      </td>

      <td>
        The type of board to create.
      </td>

      <td>
        `private`  
        `public` `share`
      </td>
    </tr>

    <tr>
      <td>
        board_name
      </td>

      <td>
        `String!`
      </td>

      <td>
        The new board's name.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_owner_ids
      </td>

      <td>
        `[ID!]`
      </td>

      <td>
        A list of the IDs of the users who will be board owners.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_owner_team_ids
      </td>

      <td>
        `[ID!]`
      </td>

      <td>
        A list of the IDs of the teams that will be board owners.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_subscriber_ids
      </td>

      <td>
        `[ID!]`
      </td>

      <td>
        A list of the IDs of the users who will subscribe to the board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_subscriber_teams_ids
      </td>

      <td>
        `[ID!]`
      </td>

      <td>
        A list of the IDs of the teams that will subscribe to the board.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        description
      </td>

      <td>
        `String`
      </td>

      <td>
        The new board's description.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        empty
      </td>

      <td>
        `Boolean`
      </td>

      <td>
        Creates an empty board without any default items.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        folder_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The board's folder ID.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        item_nickname
      </td>

      <td>
        [`ItemNicknameInput`](https://developer.monday.com/api-reference/reference/boards-other-types#itemnicknameinput)
      </td>

      <td>
        The nickname configuration for items on the board. When provided, the configuration is applied to the new board's items.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        template_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The board's template ID.*
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        workspace_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The board's workspace ID.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        prompt
      </td>

      <td>
        `String`
      </td>

      <td>
        An AI prompt to generate the board's structure and content (columns, groups, items). **Only available in versions `2026-04` and later.**
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

\**You can see your personal template IDs in the template preview screen by activating Developer Mode in monday.labs. For built-in templates, the template ID will be the board ID of the board created from the template.*

## Set board permission

Sets or updates a [board's default role/permissions](https://support.monday.com/hc/en-us/articles/115005315809-Board-permissions). Returns [`SetBoardPermissionResponse`](https://developer.monday.com/api-reference/reference/other-types#set-board-permission-response).

<Callout icon="🚧" theme="warn">
  This mutation only works for board owners on an Enterprise plan.
</Callout>

```graphql GraphQL
mutation {
  set_board_permission(
    board_id: 1234567890
    basic_role_name: viewer
  ) {
    edit_permissions
    failed_actions
  }
}
```

### Arguments

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Argument
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        basic_role_name
      </td>

      <td>
        `BoardBasicRoleName!`
      </td>

      <td>
        The role's name.
      </td>

      <td>
        `contributor` (can edit content)  
        `editor` (can edit content and structure)  
        `viewer` (read-only)
      </td>
    </tr>

    <tr>
      <td>
        board_id
      </td>

      <td>
        `ID!`
      </td>

      <td>
        The board's unique identifier.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        cross_product_collaborative
      </td>

      <td>
        `Boolean`
      </td>

      <td>
        When `true`, enables cross-product collaboration permissions for the board. **Only available in versions `2026-07` and later.**
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

## Duplicate board

Duplicates a board with all of its items and groups to a specific workspace or folder. Returns [`Board`](https://developer.monday.com/api-reference/docs/boards#fields).

An asynchronous duplication process may take some time to complete, so the query may initially return partial data.

<Callout icon="🚧" theme="warn">
  This mutation has an additional rate limit of **40** mutations per minute.
</Callout>

```graphql GraphQL
mutation {
  duplicate_board(
    board_id: 1234567890
    duplicate_type: duplicate_board_with_structure
  ) {
    board {
      id
    }
  }
}
```
```javascript JavaScript
import { ApiClient } from "@mondaydotcomorg/api";
const mondayApiClient = new ApiClient({ token: myToken });
const query = `mutation ($board: ID!) { duplicate_board(board_id: $board, duplicate_type: duplicate_board_with_structure) { board { id }}}`
const variables = {
  board: 9571351437
}
const response = await mondayApiClient.request(query, variables);
```

### Arguments

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Argument
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum Values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        board_id
      </td>

      <td>
        `ID!`
      </td>

      <td>
        The board's unique identifier.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        board_name
      </td>

      <td>
        `String`
      </td>

      <td>
        The board's name. If omitted, it will be automatically generated.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        duplicate_type
      </td>

      <td>
        `DuplicateBoardType!`
      </td>

      <td>
        The duplication type.
      </td>

      <td>
        `duplicate_board_with_pulses` (duplicate structure and items)  
        `duplicate_board_with_pulses_and_updates` (duplicate structure, items, and updates)  
        `duplicate_board_with_structure` (duplicate structure)
      </td>
    </tr>

    <tr>
      <td>
        folder_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The destination folder within the destination workspace. Required if you are duplicating to another workspace. If omitted, it will default to the original board's folder.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        keep_subscribers
      </td>

      <td>
        `Boolean`
      </td>

      <td>
        Whether to duplicate the subscribers to the new board. Defaults to false.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        workspace_id
      </td>

      <td>
        `ID`
      </td>

      <td>
        The destination workspace. If omitted, it will default to the original board's workspace.
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

## Update board

Updates a board. Returns a JSON object that confirms whether the update was successful and returns the updated board metadata.

```graphql GraphQL
mutation {
  update_board(
    board_id: 1234567890
    board_attribute: description
    new_value: "This is my new description"
  ) 
}
```
```javascript JavaScript
import { ApiClient } from "@mondaydotcomorg/api";
const mondayApiClient = new ApiClient({ token: myToken });
const query = `mutation ($desc: String!) { update_board (board_id: 1234567890, board_attribute: description, new_value: $desc)}`
const variables = {
  desc: "This is my new description"
}
const response = await mondayApiClient.request(query, variables);
```

### Arguments

<Table align={["left","left","left","left"]}>
  <thead>
    <tr>
      <th>
        Argument
      </th>

      <th>
        Type
      </th>

      <th>
        Description
      </th>

      <th>
        Enum Values
      </th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td>
        board_attribute
      </td>

      <td>
        `BoardAttributes!`
      </td>

      <td>
        The board's attribute to update.
      </td>

      <td>
        `communication`  
        `description`  
        [`item_nickname`](https://developer.monday.com/api-reference/reference/boards-other-types#item_nickname) (version `2026-04` and later)
        `name`
      </td>
    </tr>

    <tr>
      <td>
        board_id
      </td>

      <td>
        `ID!`
      </td>

      <td>
        The board's unique identifier.
      </td>

      <td>

      </td>
    </tr>

    <tr>
      <td>
        new_value
      </td>

      <td>
        `String!`
      </td>

      <td>
        The new attribute value.
      </td>

      <td>

      </td>
    </tr>
  </tbody>
</Table>

## Update board hierarchy

Updates a board's position, workspace, or product. Returns [`UpdateBoardHierarchyResult`](https://developer.monday.com/api-reference/reference/other-types#update-board-hierarchy-result).

```graphql GraphQL
mutation {
  update_board_hierarchy(
    board_id: 1234567890,
    attributes: {
      account_product_id: 54321
      workspace_id: 12345
      folder_id: 9876543210
      position: {
        object_id: "15",
        object_type: Overview,
        is_after: true
      }
    }
  ) {
    success
  }
}
```

### Arguments

| Argument   | Type                                                                                                                                               | Description                       |
| :--------- | :------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------- |
| attributes | [`UpdateBoardHierarchyAttributesInput!`](https://developer.monday.com/api-reference/reference/other-types#update-board-hierarchy-attributes-input) | The board's attributes to update. |
| board\_id  | `ID!`                                                                                                                                              | The board's unique identifier.    |

## Archive board

Archives a board. Returns [`Board`](https://developer.monday.com/api-reference/docs/boards#fields).

```graphql GraphQL
mutation {
  archive_board(
    board_id: 1234567890
  ) {
    id
  }
}
```
```javascript JavaScript
import { ApiClient } from "@mondaydotcomorg/api";
const mondayApiClient = new ApiClient({ token: myToken });
const query = `mutation ($board: ID!) { archive_board (board_id: $board) { id }}`
const variables = {
  board: 1234567
}
const response = await mondayApiClient.request(query, variables);
```

### Arguments

| Argument  | Type  | Description                    |
| :-------- | :---- | :----------------------------- |
| board\_id | `ID!` | The board's unique identifier. |

## Delete board

Deletes a board. Returns [`Board`](https://developer.monday.com/api-reference/docs/boards#fields).

```graphql GraphQL
mutation {
  delete_board(
    board_id: 1234567890
  ) {
    id
  }
}
```
```javascript JavaScript
import { ApiClient } from "@mondaydotcomorg/api";
const mondayApiClient = new ApiClient({ token: myToken });

const query = `mutation ($board: ID!) { delete_board (board_id: $board) { id }}`
const variables = {
  board: 1234567
}
const response = await mondayApiClient.request(query, variables);
```

### Arguments

| Argument  | Type  | Description                    |
| :-------- | :---- | :----------------------------- |
| board\_id | `ID!` | The board's unique identifier. |