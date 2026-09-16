#!/usr/bin/env ruby
# Small dependency-free Markdown-to-printable-HTML renderer for the two handoff guides.
require "cgi"

input, output = ARGV
abort "usage: render_pdf.rb INPUT.md OUTPUT.html" unless input && output
lines = File.read(input, encoding: "UTF-8").lines.map(&:chomp)
html = []
html << "<!doctype html><html lang='th'><head><meta charset='utf-8'><title>#{CGI.escapeHTML(File.basename(input))}</title>"
html << <<~CSS
  <style>
  @page { size: A4; margin: 17mm 16mm 18mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, 'Noto Sans Thai', sans-serif; color: #18212f; font-size: 10.5pt; line-height: 1.55; }
  h1 { color: #0b3b5c; font-size: 24pt; border-bottom: 3px solid #e49b2d; padding-bottom: 8px; page-break-after: avoid; }
  h2 { color: #0b3b5c; font-size: 16pt; margin-top: 22px; border-bottom: 1px solid #cad5df; page-break-after: avoid; }
  h3 { color: #176b82; font-size: 12.5pt; page-break-after: avoid; }
  p { margin: 7px 0; } ul { margin-top: 4px; } li { margin: 3px 0; }
  code { background: #eef3f6; padding: 1px 4px; border-radius: 3px; }
  pre { background: #f3f6f8; border: 1px solid #d5dee5; border-left: 4px solid #176b82; padding: 10px; white-space: pre-wrap; font-size: 8.5pt; page-break-inside: avoid; }
  table { width: 100%; border-collapse: collapse; margin: 9px 0 14px; font-size: 9pt; page-break-inside: avoid; }
  th { background: #0b3b5c; color: white; text-align: left; } th, td { border: 1px solid #bccbd5; padding: 5px 7px; vertical-align: top; }
  blockquote { border-left: 4px solid #e49b2d; padding-left: 10px; color: #526271; }
  .cover { color: #526271; margin-bottom: 22px; } .pagebreak { page-break-before: always; }
  </style></head><body>
CSS
in_code = false
in_table = false
paragraph = []
flush = lambda do
  unless paragraph.empty?
    text = paragraph.map { |l| l.end_with?("  ") ? l.rstrip + "<br>" : l }.join(" ").gsub(/`([^`]+)`/) { "<code>#{CGI.escapeHTML($1)}</code>" }
    html << "<p>#{text}</p>"
    paragraph.clear
  end
end
close_table = lambda do
  if in_table
    html << "</tbody></table>"
    in_table = false
  end
end
lines.each do |line|
  if line.start_with?("```")
    flush.call; close_table.call
    if in_code
      html << "</pre>"; in_code = false
    else
      html << "<pre>"; in_code = true
    end
    next
  end
  if in_code
    html << CGI.escapeHTML(line); next  # html.join("\n") already adds the line break
  end
  if line.strip.empty?
    flush.call; next
  end
  if line.start_with?("# ")
    flush.call; close_table.call; html << "<h1>#{CGI.escapeHTML(line[2..])}</h1>"; next
  elsif line.start_with?("## ")
    flush.call; close_table.call; html << "<h2>#{CGI.escapeHTML(line[3..])}</h2>"; next
  elsif line.start_with?("### ")
    flush.call; close_table.call; html << "<h3>#{CGI.escapeHTML(line[4..])}</h3>"; next
  end
  if line.start_with?("|")
    flush.call
    # limit -1 keeps the trailing empty field, so [1..-2] no longer drops the last column
    cells = line.split("|", -1)[1..-2].map do |cell|
      CGI.escapeHTML(cell.strip).gsub(/`([^`]+)`/) { "<code>#{$1}</code>" }
    end
    if line.match?(/^\|\s*:?-+:?\s*\|/)
      next
    elsif !in_table
      html << "<table><thead><tr>#{cells.map { |c| "<th>#{c}</th>" }.join}</tr></thead><tbody>"; in_table = true
    else
      html << "<tr>#{cells.map { |c| "<td>#{c}</td>" }.join}</tr>"
    end
    next
  else
    close_table.call
  end
  if line.start_with?("- ")
    flush.call
    html << "<ul><li>#{line[2..].gsub(/`([^`]+)`/) { "<code>#{CGI.escapeHTML($1)}</code>" }}</li></ul>"
  else
    paragraph << line
  end
end
flush.call; close_table.call; html << "</body></html>"
File.write(output, html.join("\n"), encoding: "UTF-8")
