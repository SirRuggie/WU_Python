import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import ModerationPreviewCard from "./ModerationPreviewCard";

function profileText(value: string) {
  return renderToStaticMarkup(
    createElement(ModerationPreviewCard, {
      payload: { components: [{ type: 10, content: value }] },
      names: { "987654321": "Fallback moderator" },
    }),
  );
}

it("renders a masked Discord profile as an exact safe anchor", () => {
  const html = profileText(
    "[Sagan](https://discord.com/users/463458603324669964) left",
  );
  expect(html.match(/<a /g)).toHaveLength(1);
  expect(html).toContain(
    '<a href="https://discord.com/users/463458603324669964" target="_blank" rel="noopener noreferrer">Sagan</a> left',
  );
});

it("unescapes profile labels as React text, including punctuation and broken mentions", () => {
  const html = profileText(
    "[name\\] \\( \\) \\* \\_ \\\\ @\u200beveryone](https://discord.com/users/123)",
  );
  expect(html).toContain(">name] ( ) * _ \\ @everyone</a>");
  expect(html).not.toContain("\u200b");
  expect(
    profileText("[<script>alert(1)</script>](https://discord.com/users/123)"),
  ).toContain("&lt;script&gt;alert(1)&lt;/script&gt;</a>");
});

it.each([
  "[x](https://evil.example)",
  "[x](javascript:alert(1))",
  "[x](https://discord.com/users/12a)",
  "[x](https://discord.com/users/12?redirect=https://evil.example)",
  "[x](https://discord.com.evil/users/12)",
  "[x](https://discord.com/users/12/)",
  "[name\nnext](https://discord.com/users/12)",
  "[unclosed](https://discord.com/users/12",
  "\\[label](https://discord.com/users/123)",
  "[x](https://evil.example/[label](https://discord.com/users/123))",
  "[outer [Sagan](https://discord.com/users/123)](https://evil.example)",
])("keeps unsupported or malformed link text inert: %s", (value) => {
  const html = profileText(value);
  expect(html).not.toContain("<a ");
});

it("keeps profile, mention fallback and timestamp tokens on the same line", () => {
  const html = profileText(
    "[Sagan](https://discord.com/users/123) by <@987654321> · <t:1717243200:f>",
  );
  expect(html).toContain(">Sagan</a> by ");
  expect(html).toContain('title="987654321">Fallback moderator</span>');
  expect(html).toContain('dateTime="2024-06-01T12:00:00.000Z"');
});

it("escapes hostile HTML after a valid profile and permits parenthetical profile text", () => {
  const html = profileText(
    "(see [Sagan](https://discord.com/users/123)) <img onerror=alert(1)>",
  );
  expect(html.match(/href="([^"]+)"/g)).toEqual([
    'href="https://discord.com/users/123"',
  ]);
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img onerror=alert(1)&gt;");
});

it("renders component text safely and allows only Discord profile links", () => {
  const html = renderToStaticMarkup(
    createElement(ModerationPreviewCard, {
      payload: {
        flags: 32768,
        components: [
          {
            type: 17,
            accent_color: 15112501,
            components: [
              { type: 10, content: "### 👢 Member kicked" },
              {
                type: 10,
                content:
                  "**Reason**\n<script>alert(1)</script> · <@123456789> · <t:1717243200:f>",
              },
              {
                type: 9,
                components: [{ type: 10, content: "**Example Member**" }],
                accessory: {
                  type: 11,
                  media: {
                    url: "https://cdn.discordapp.com/embed/avatars/0.png",
                  },
                },
              },
              {
                type: 1,
                components: [
                  {
                    type: 2,
                    label: "View profile",
                    url: "https://discord.com/users/123456789",
                  },
                  { type: 2, label: "Unsafe", url: "javascript:alert(1)" },
                ],
              },
            ],
          },
        ],
      },
    }),
  );
  expect(html).toContain("Member kicked");
  expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  expect(html).toContain('href="https://discord.com/users/123456789"');
  expect(html).not.toContain('href="javascript:');
  expect(html).toContain('title="123456789">Unknown member</span>');
  expect(html).not.toContain("@123456789");
  expect(html).toContain('dateTime="2024-06-01T12:00:00.000Z"');
  expect(html).toContain("Sample member avatar");
});

it("renders the forum embed payload separately", () => {
  const html = renderToStaticMarkup(
    createElement(ModerationPreviewCard, {
      forum: true,
      payload: {
        embeds: [
          {
            description: "Forum starter for <@123456789>\n**Reason**: <script>",
            color: 15112501,
            thumbnail: {
              url: "https://cdn.discordapp.com/embed/avatars/0.png",
            },
          },
        ],
      },
    }),
  );
  expect(html).toContain("Forum starter");
  expect(html).toContain("Forum starter preview");
  expect(html).toContain('title="123456789">Unknown member</span>');
  expect(html).not.toContain("@123456789");
  expect(html).toContain("&lt;script&gt;");
});
