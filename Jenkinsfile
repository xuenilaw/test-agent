def review = [candidates: [], possible_false_passes: [], analysis_sha256: null]
def decision = [status: 'not_required', approved: [], approved_by: null, analysis_sha256: null]
def finalReportsReady = false

pipeline {
    agent none
    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }
    triggers { pollSCM('H/5 * * * *') }
    environment {
        VISION_PROVIDER = 'clef'
        VISION_MODEL = 'cloudflare/clef'
        AUDIT_MODEL = 'claude-haiku-5-5'
        PLAYWRIGHT_BROWSERS_PATH = '/ms-playwright'
        UV_PROJECT_ENVIRONMENT = '/tmp/wbs-ci-venv'
        UV_CACHE_DIR = '/tmp/wbs-uv-cache'
        UV_PYTHON_DOWNLOADS = 'never'
        JIRA_SITE = 'https://lawxueni.atlassian.net'
        JIRA_PROJECT = 'WBSFP'
    }
    stages {
        stage('Run tests and audit') {
            agent {
                docker {
                    image 'mcr.microsoft.com/playwright/python:v1.63.0-noble'
                    args '--user 0:0 --ipc=host'
                }
            }
            options { timeout(time: 30, unit: 'MINUTES') }
            stages {
                stage('Setup') {
                    steps {
                        deleteDir()
                        checkout scm
                        sh '''
                            test ! -f .env
                            python -m pip install --disable-pip-version-check uv==0.12.17
                            uv sync --locked
                        '''
                    }
                }
                stage('Unit tests') {
                    steps { sh 'uv run python -m unittest discover -s tests -v' }
                }
                stage('Test suite') {
                    steps {
                        withCredentials([
                            string(credentialsId: 'wbs-openai-api-key', variable: 'OPENAI_API_KEY'),
                            string(credentialsId: 'wbs-openai-base-url', variable: 'OPENAI_BASE_URL'),
                            string(credentialsId: 'wbs-openai-model', variable: 'OPENAI_MODEL'),
                            string(credentialsId: 'wbs-openrouter-api-key', variable: 'OPENROUTER_API_KEY'),
                            string(credentialsId: 'wbs-anthropic-api-key', variable: 'ANTHROPIC_API_KEY')
                        ]) {
                            script {
                                def code = sh(returnStatus: true, script: '''
                                    set +x
                                    uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json
                                ''')
                                def result = sh(returnStdout: true, script: "python ci/suite_result.py ${code}").trim()
                                sh 'uv run python ci/prepare_reports.py'
                                if (result == 'UNSTABLE') {
                                    unstable('Suite contains FAILED/BLOCKED checks; inspect Test Result and Test Report.')
                                } else if (result != 'SUCCESS') {
                                    error("Suite infrastructure error or incomplete evidence (exit ${code}).")
                                }
                            }
                        }
                    }
                    post {
                        always {
                            junit testResults: 'reports/junit.xml', allowEmptyResults: false
                        }
                    }
                }
                stage('Audit analysis') {
                    steps {
                        script {
                            def auditCode = -1
                            catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE', catchInterruptions: false) {
                                withCredentials([
                                    string(credentialsId: 'wbs-anthropic-api-key', variable: 'ANTHROPIC_API_KEY')
                                ]) {
                                    auditCode = sh(returnStatus: true, script: '''
                                        set +x
                                        uv run python -m test_agent audit-agent artifacts/suite-*
                                    ''')
                                }
                            }
                            if (auditCode != 0) {
                                echo 'Audit unavailable; record unaudited cases without model calls.'
                                sh(returnStatus: true, script: 'uv run python -m test_agent audit-agent artifacts/suite-* --unavailable')
                            }
                            def packageCode = sh(returnStatus: true, script: 'uv run python ci/prepare_reports.py')
                            if (packageCode == 0 && fileExists('reports/audit_review.json')) {
                                review = readJSON(file: 'reports/audit_review.json', returnPojo: true)
                                currentBuild.description = review.summary + (review.attention_details ? ' ' + review.attention_details.join('; ') : '')
                                if (review.banner) { currentBuild.description += ' ' + review.banner }
                                if (review.credential_warning) {
                                    echo review.credential_warning
                                    currentBuild.description += ' ' + review.credential_warning
                                }
                                decision.analysis_sha256 = review.analysis_sha256
                            }
                        }
                    }
                }
            }
            post {
                always {
                    stash name: 'reports', includes: 'reports/**', allowEmpty: true
                    // Publish before input so the human can inspect the full report while waiting.
                    archiveArtifacts artifacts: 'reports/**', fingerprint: true, allowEmptyArchive: true
                    publishHTML(target: [reportDir: 'reports', reportFiles: 'report.html', reportName: 'Test Report',
                        keepAll: true, alwaysLinkToLastBuild: true, allowMissing: true])
                }
            }
        }
        stage('Review tickets') {
            agent none
            when { expression { !review.candidates.isEmpty() } }
            steps {
                script {
                    def choices = review.candidates.collect { f ->
                        booleanParam(name: f.finding_id, defaultValue: false, description: f.description)
                    }
                    try {
                        def answer
                        timeout(time: 30, unit: 'MINUTES') {
                            answer = input(message: "AI suggestion, verify before acting. Select only tickets you approve.\n" +
                                "${review.attention_count} attention items (information only). ${review.summary}\n" +
                                "Full analysis: ${env.BUILD_URL}artifact/reports/audit_analysis.md",
                                ok: 'Record decision', submitterParameter: 'APPROVER', parameters: choices)
                        }
                        decision.approved = review.candidates.findAll { answer[it.finding_id] == true }.collect { it.finding_id }
                        decision.approved_by = answer.APPROVER
                        decision.status = decision.approved.isEmpty() ? 'declined' : 'approved'
                    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException ignored) {
                        decision.status = 'timeout_or_abort'
                        decision.approved = []
                        echo 'No approval recorded. Nothing will be sent to Jira; test result is preserved.'
                    }
                }
            }
        }
        stage('Record decision and Jira') {
            agent {
                docker {
                    image 'mcr.microsoft.com/playwright/python:v1.63.0-noble'
                    args '--user 0:0 --ipc=host'
                }
            }
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                deleteDir()
                checkout scm
                unstash 'reports'
                script {
                    writeJSON file: 'reports/jira_decision.json', json: decision, pretty: 2
                    if (!decision.approved.isEmpty()) {
                        catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', catchInterruptions: false) {
                            sh '''
                                python -m pip install --disable-pip-version-check uv==0.12.17
                                uv sync --locked
                            '''
                            withCredentials([usernamePassword(credentialsId: 'wbs-jira', usernameVariable: 'JIRA_EMAIL', passwordVariable: 'JIRA_API_TOKEN')]) {
                                withEnv(["APPROVED_FINDINGS=${decision.approved.join(',')}", "TEST_REPORT_URL=${env.BUILD_URL}Test_20Report/"]) {
                                    def code = sh(returnStatus: true, script: '''
                                        set +x
                                        uv run python -m test_agent jira create reports --approved "$APPROVED_FINDINGS" --send
                                    ''')
                                    if (code != 0) { unstable('Jira action failed; inspect jira_results.json. Test reports are retained.') }
                                }
                            }
                        }
                        if (fileExists('reports/jira_results.json')) {
                            def jira = readJSON(file: 'reports/jira_results.json', returnPojo: true)
                            currentBuild.description = (currentBuild.description ?: '') + ' · ' + jira.issues.collect { it.url }.join(' · ')
                        }
                    }
                }
            }
            post {
                always {
                    script {
                        if (fileExists('reports/report.html')) {
                            stash name: 'reports-final', includes: 'reports/**'
                            finalReportsReady = true
                        }
                    }
                }
            }
        }
    }
    post {
        always {
            // Allocate storage briefly for publication, never while waiting for approval.
            node('') {
                deleteDir()
                script {
                    try { unstash(finalReportsReady ? 'reports-final' : 'reports') }
                    catch (Exception ignored) { echo 'No saved reports available; inspect the first failed work stage.' }
                }
                archiveArtifacts artifacts: 'reports/**', fingerprint: true, allowEmptyArchive: true
                publishHTML(target: [reportDir: 'reports', reportFiles: 'report.html', reportName: 'Test Report',
                    keepAll: true, alwaysLinkToLastBuild: true, allowMissing: true])
            }
        }
    }
}
