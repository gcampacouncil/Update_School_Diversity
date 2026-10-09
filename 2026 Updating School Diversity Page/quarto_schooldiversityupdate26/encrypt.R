# encrypt.R

# 1. LOAD THE LIBRARY
library(staticryptR)

# 2. DEFINE SITE DETAILS
site_password <- "council26"

# 3. RUN THE ENCRYPTION
staticryptr(
  files = "docs",
  directory = ".",
  password = site_password,
  short = TRUE,
  recursive = TRUE,
  template_color_primary = "#05014a", # Using your site's accent color
  template_color_secondary = "#f9f9f3",
  template_title = "School Diversity in NYC",
  template_instructions = "This content is protected. Please enter the password or contact the NYC Council Data Team for access.",
  template_button = "Unlock"
)
