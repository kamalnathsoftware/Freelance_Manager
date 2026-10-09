import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlatformBadge } from "@/components/platform-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

describe("ui", () => {
  it("renders a button", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });
  it("shows input errors accessibly", () => {
    render(<Input label="Email" error="Required" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Required");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });
  it("renders platform badge", () => {
    render(<PlatformBadge platform="fiverr" />);
    expect(screen.getByText("fiverr")).toBeInTheDocument();
  });
});
