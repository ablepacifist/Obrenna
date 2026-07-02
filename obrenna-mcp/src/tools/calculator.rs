use anyhow::{anyhow, Result};
use serde_json::{json, Value};

pub fn definition() -> Value {
    json!({
        "name": "calculator",
        "description": "Evaluate mathematical expressions safely",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate (supports +, -, *, /, %, parentheses)"
                }
            },
            "required": ["expression"]
        }
    })
}

pub async fn execute(args: &Value) -> Result<Value> {
    let expression = args
        .get("expression")
        .and_then(|v| v.as_str())
        .ok_or_else(|| anyhow!("Missing or invalid 'expression' parameter"))?;

    let result = match evaluate_expression(expression) {
        Ok(result) => json!({ "result": result }),
        Err(e) => json!({ "error": e.to_string() }),
    };

    Ok(json!({
        "content": [{
            "type": "text",
            "text": result.to_string()
        }],
        "isError": matches!(result.get("error"), Some(_))
    }))
}

fn evaluate_expression(expr: &str) -> Result<f64> {
    let expr = expr.trim();
    if expr.is_empty() {
        return Err(anyhow!("Empty expression"));
    }

    let mut parser = ExprParser::new(expr);
    let result = parser.parse_expression()?;
    if parser.pos != parser.tokens.len() {
        return Err(anyhow!(
            "Unexpected trailing token: {:?}",
            parser.tokens[parser.pos]
        ));
    }
    Ok(result)
}

struct ExprParser {
    tokens: Vec<Token>,
    pos: usize,
}

#[derive(Debug, Clone, PartialEq)]
enum Token {
    Number(f64),
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    LParen,
    RParen,
}

impl ExprParser {
    fn new(expr: &str) -> Self {
        let tokens = Self::tokenize(expr);
        ExprParser { tokens, pos: 0 }
    }

    fn tokenize(expr: &str) -> Vec<Token> {
        let mut tokens = Vec::new();
        let mut i = 0;
        let chars: Vec<char> = expr.chars().collect();

        while i < chars.len() {
            match chars[i] {
                ' ' | '\t' => {
                    i += 1;
                }
                '+' => {
                    tokens.push(Token::Plus);
                    i += 1;
                }
                '-' => {
                    i += 1;
                    if i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '.') {
                        let start = i;
                        while i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '.') {
                            i += 1;
                        }
                        let num_str: String = chars[start..i].iter().collect();
                        if let Ok(num) = format!("-{}", num_str).parse::<f64>() {
                            tokens.push(Token::Number(num));
                        }
                    } else {
                        tokens.push(Token::Minus);
                    }
                }
                '*' => {
                    tokens.push(Token::Star);
                    i += 1;
                }
                '/' => {
                    tokens.push(Token::Slash);
                    i += 1;
                }
                '%' => {
                    tokens.push(Token::Percent);
                    i += 1;
                }
                '(' => {
                    tokens.push(Token::LParen);
                    i += 1;
                }
                ')' => {
                    tokens.push(Token::RParen);
                    i += 1;
                }
                c if c.is_ascii_digit() || c == '.' => {
                    let start = i;
                    while i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '.') {
                        i += 1;
                    }
                    let num_str: String = chars[start..i].iter().collect();
                    if let Ok(num) = num_str.parse::<f64>() {
                        tokens.push(Token::Number(num));
                    }
                }
                _ => {
                    i += 1;
                }
            }
        }

        tokens
    }

    fn parse_expression(&mut self) -> Result<f64> {
        self.parse_additive()
    }

    fn parse_additive(&mut self) -> Result<f64> {
        let mut left = self.parse_multiplicative()?;

        while self.pos < self.tokens.len() {
            match &self.tokens[self.pos] {
                Token::Plus => {
                    self.pos += 1;
                    let right = self.parse_multiplicative()?;
                    left += right;
                }
                Token::Minus => {
                    self.pos += 1;
                    let right = self.parse_multiplicative()?;
                    left -= right;
                }
                _ => break,
            }
        }

        Ok(left)
    }

    fn parse_multiplicative(&mut self) -> Result<f64> {
        let mut left = self.parse_primary()?;

        while self.pos < self.tokens.len() {
            match &self.tokens[self.pos] {
                Token::Star => {
                    self.pos += 1;
                    let right = self.parse_primary()?;
                    left *= right;
                }
                Token::Slash => {
                    self.pos += 1;
                    let right = self.parse_primary()?;
                    if right == 0.0 {
                        return Err(anyhow!("Division by zero"));
                    }
                    left /= right;
                }
                Token::Percent => {
                    self.pos += 1;
                    let right = self.parse_primary()?;
                    if right == 0.0 {
                        return Err(anyhow!("Modulo by zero"));
                    }
                    left %= right;
                }
                _ => break,
            }
        }

        Ok(left)
    }

    fn parse_primary(&mut self) -> Result<f64> {
        if self.pos >= self.tokens.len() {
            return Err(anyhow!("Unexpected end of expression"));
        }

        match &self.tokens[self.pos].clone() {
            Token::Number(n) => {
                self.pos += 1;
                Ok(*n)
            }
            Token::LParen => {
                self.pos += 1;
                let result = self.parse_expression()?;
                if self.pos >= self.tokens.len() || self.tokens[self.pos] != Token::RParen {
                    return Err(anyhow!("Missing closing parenthesis"));
                }
                self.pos += 1;
                Ok(result)
            }
            Token::Minus => {
                self.pos += 1;
                Ok(-self.parse_primary()?)
            }
            _ => Err(anyhow!("Unexpected token in expression")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evaluates_simple_expression() {
        assert_eq!(evaluate_expression("6*7").unwrap(), 42.0);
    }

    #[test]
    fn rejects_trailing_tokens() {
        // Before the fix, this silently returned 2 (stopping after the
        // first number and ignoring "2" that follows it).
        assert!(evaluate_expression("2 2").is_err());
    }

    #[test]
    fn rejects_trailing_tokens_after_parens() {
        assert!(evaluate_expression("(1+1)3").is_err());
    }

    #[test]
    fn division_by_zero_is_an_error() {
        assert!(evaluate_expression("1/0").is_err());
    }

    #[test]
    fn nested_parens_work() {
        assert_eq!(evaluate_expression("((2+3)*2)").unwrap(), 10.0);
    }
}
