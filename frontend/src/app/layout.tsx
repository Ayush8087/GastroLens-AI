import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GastroLens — A little hungry. A lot more certain.",
  description: "Find real restaurants, read actual menus, and compare dishes with evidence behind every detail.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
