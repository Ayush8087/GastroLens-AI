import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GastroLens — Restaurant Research",
  description: "Find restaurants with source-linked menus, printed prices, and clear evidence.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
