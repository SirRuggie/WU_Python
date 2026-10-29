import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ImageGallery } from "./CommandImageLibrary";

it("shows the Image gallery page title", () => {
  expect(renderToStaticMarkup(<ImageGallery />)).toContain(
    "<h1>Image gallery</h1>",
  );
});
