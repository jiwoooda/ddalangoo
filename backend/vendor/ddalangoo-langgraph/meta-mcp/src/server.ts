import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import process from "node:process";
import { SearchProductsParamsSchema, searchProducts } from "./search.js";

const server = new McpServer({
  name: "meta-shopping-mcp",
  version: "1.0.0",
});

server.tool(
  "search_products",
  SearchProductsParamsSchema.shape,
  async (params) => {
    const result = await searchProducts(params);

    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    };
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[meta-shopping-mcp] server started");
}

main().catch((err) => {
  console.error("[meta-shopping-mcp] fatal error:", err);
  process.exit(1);
});
