use anyhow::{anyhow, Result};
use regex::Regex;
use serde_json::{json, Value};

pub fn definition() -> Value {
    json!({
        "name": "web_search",
        "description": "Return web search snippets with source URLs only. No full-page fetch. Returns an array of result objects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    })
}

pub async fn execute(args: &Value) -> Result<Value> {
    let query = args
        .get("query")
        .and_then(|v| v.as_str())
        .ok_or_else(|| anyhow!("Missing or invalid 'query' parameter"))?;

    let max_results = args
        .get("max_results")
        .and_then(|v| v.as_u64())
        .unwrap_or(10) as usize;

    match search_duckduckgo(query, max_results).await {
        Ok(results) => Ok(json!({
            "content": [{
                "type": "text",
                "text": json!(results).to_string()
            }],
            "isError": false
        })),
        Err(e) => Ok(json!({
            "content": [{
                "type": "text",
                "text": json!({ "error": e.to_string() }).to_string()
            }],
            "isError": true
        })),
    }
}

async fn search_duckduckgo(query: &str, max_results: usize) -> Result<Vec<SearchResult>> {
    let client = reqwest::Client::new();
    let max_results = max_results.clamp(1, 10);

    let html_results = search_duckduckgo_html(&client, query, max_results).await?;
    if !html_results.is_empty() {
        return Ok(html_results);
    }

    let url = format!("https://api.duckduckgo.com/?q={}&format=json", urlencoding::encode(query));

    let response = client
        .get(&url)
        .header("User-Agent", "obrenna-mcp/0.1.0")
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await?;

    let data: DuckDuckGoResponse = response.json().await?;

    let mut results = Vec::new();

    // Add instant answer if available
    if !data.abstract_text.is_empty() {
        results.push(SearchResult {
            title: data.heading.unwrap_or_else(|| "Answer".to_string()),
            url: data.abstract_url.unwrap_or_default(),
            snippet: data.abstract_text,
        });
    }

    // Add related topics
    for topic in data.related_topics.iter().take(max_results.saturating_sub(results.len())) {
        if let Some(text) = &topic.text {
            results.push(SearchResult {
                title: text.clone(),
                url: topic.first_url.clone().unwrap_or_default(),
                snippet: topic.text.clone().unwrap_or_default(),
            });
        }
    }

    Ok(results)
}

async fn search_duckduckgo_html(
    client: &reqwest::Client,
    query: &str,
    max_results: usize,
) -> Result<Vec<SearchResult>> {
    let response = client
        .get("https://html.duckduckgo.com/html/")
        .query(&[("q", query)])
        .header("User-Agent", "obrenna-mcp/0.1.0")
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await?;

    let html = response.text().await?;
    Ok(parse_duckduckgo_html(&html, max_results))
}

fn parse_duckduckgo_html(html: &str, max_results: usize) -> Vec<SearchResult> {
    let title_re = Regex::new(r#"(?is)<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>"#).unwrap();
    let snippet_re = Regex::new(r#"(?is)<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>|<div\s+[^>]*class="result__snippet"[^>]*>(.*?)</div>"#).unwrap();

    let mut results = Vec::new();
    for title_caps in title_re.captures_iter(html) {
        let Some(full_match) = title_caps.get(0) else { continue; };
        let raw_url = title_caps.get(1).map(|m| m.as_str()).unwrap_or_default();
        let raw_title = title_caps.get(2).map(|m| m.as_str()).unwrap_or_default();

        let snippet_window_end = (full_match.end() + 5000).min(html.len());
        let snippet_window = &html[full_match.end()..snippet_window_end];
        let raw_snippet = snippet_re
            .captures(snippet_window)
            .and_then(|caps| caps.get(1).or_else(|| caps.get(2)))
            .map(|m| m.as_str())
            .unwrap_or_default();

        let title = clean_html(raw_title);
        let url = clean_url(raw_url);
        if title.is_empty() || url.is_empty() {
            continue;
        }

        results.push(SearchResult {
            title,
            url,
            snippet: clean_html(raw_snippet),
        });
        if results.len() >= max_results {
            break;
        }
    }
    results
}

fn clean_html(input: &str) -> String {
    let tag_re = Regex::new(r#"(?is)<[^>]+>"#).unwrap();
    tag_re
        .replace_all(input, "")
        .replace("&amp;", "&")
        .replace("&quot;", "\"")
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .trim()
        .to_string()
}

fn clean_url(input: &str) -> String {
    let cleaned = input.replace("&amp;", "&").trim().to_string();
    if let Some(start) = cleaned.find("uddg=") {
        let encoded = &cleaned[start + 5..];
        let end = encoded.find('&').unwrap_or(encoded.len());
        if let Ok(decoded) = urlencoding::decode(&encoded[..end]) {
            return decoded.into_owned();
        }
    }
    if cleaned.starts_with("//") {
        return format!("https:{}", cleaned);
    }
    cleaned
}

#[derive(serde::Deserialize)]
struct DuckDuckGoResponse {
    #[serde(rename = "AbstractText")]
    abstract_text: String,
    #[serde(rename = "AbstractURL")]
    abstract_url: Option<String>,
    #[serde(rename = "Heading")]
    heading: Option<String>,
    #[serde(rename = "RelatedTopics")]
    related_topics: Vec<RelatedTopic>,
}

#[derive(serde::Deserialize)]
struct RelatedTopic {
    #[serde(rename = "Text")]
    text: Option<String>,
    #[serde(rename = "FirstURL")]
    first_url: Option<String>,
}

#[derive(serde::Serialize, Debug)]
struct SearchResult {
    title: String,
    url: String,
    snippet: String,
}
