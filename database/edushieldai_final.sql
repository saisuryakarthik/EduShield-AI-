-- MySQL dump 10.13  Distrib 8.0.46, for Win64 (x86_64)
--
-- Host: localhost    Database: edushieldai
-- ------------------------------------------------------
-- Server version	8.0.45

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `account_activation_otps`
--

DROP TABLE IF EXISTS `account_activation_otps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `account_activation_otps` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(20) NOT NULL,
  `code_hash` char(64) DEFAULT NULL,
  `attempts` int NOT NULL DEFAULT '0',
  `locked` tinyint(1) NOT NULL DEFAULT '0',
  `used` tinyint(1) NOT NULL DEFAULT '0',
  `expires_at` datetime NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_activation_user` (`user_id`),
  CONSTRAINT `fk_activation_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `account_activation_otps`
--

LOCK TABLES `account_activation_otps` WRITE;
/*!40000 ALTER TABLE `account_activation_otps` DISABLE KEYS */;
INSERT INTO `account_activation_otps` VALUES (1,'24STUCHH010221',NULL,1,0,1,'2026-10-19 22:34:21','2026-10-19 22:29:21'),(2,'24STUCHH010238',NULL,0,0,1,'2026-10-20 11:13:49','2026-10-20 11:08:49');
/*!40000 ALTER TABLE `account_activation_otps` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `account_recoveries`
--

DROP TABLE IF EXISTS `account_recoveries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `account_recoveries` (
  `recovery_id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` varchar(20) NOT NULL,
  `requested_by` varchar(20) NOT NULL,
  `reason` varchar(500) NOT NULL,
  `status` enum('pending','verified','completed','expired','revoked','failed') NOT NULL DEFAULT 'pending',
  `code_hash` char(64) DEFAULT NULL,
  `attempts` int NOT NULL DEFAULT '0',
  `max_attempts` int NOT NULL DEFAULT '3',
  `locked` tinyint(1) NOT NULL DEFAULT '0',
  `verified_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `expires_at` datetime NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`recovery_id`),
  KEY `idx_recovery_user` (`user_id`),
  KEY `idx_recovery_status` (`status`),
  KEY `fk_recovery_requester` (`requested_by`),
  CONSTRAINT `fk_recovery_requester` FOREIGN KEY (`requested_by`) REFERENCES `users` (`user_id`),
  CONSTRAINT `fk_recovery_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `account_recoveries`
--

LOCK TABLES `account_recoveries` WRITE;
/*!40000 ALTER TABLE `account_recoveries` DISABLE KEYS */;
/*!40000 ALTER TABLE `account_recoveries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ai_assessment_status`
--

DROP TABLE IF EXISTS `ai_assessment_status`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_assessment_status` (
  `request_id` varchar(30) NOT NULL,
  `status` enum('PENDING','COMPLETED','FAILED') NOT NULL DEFAULT 'PENDING',
  `attempts` int NOT NULL DEFAULT '0',
  `last_error` varchar(500) DEFAULT NULL,
  `last_attempt_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`request_id`),
  KEY `idx_ai_assessment_status` (`status`),
  KEY `idx_ai_assessment_updated` (`updated_at`),
  CONSTRAINT `fk_ai_status_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ai_assessment_status`
--

LOCK TABLES `ai_assessment_status` WRITE;
/*!40000 ALTER TABLE `ai_assessment_status` DISABLE KEYS */;
INSERT INTO `ai_assessment_status` VALUES ('REQ0127EBD0BD52','COMPLETED',1,NULL,'2026-10-22 18:44:58','2026-10-22 18:44:58','2026-10-22 18:44:58','2026-10-22 18:44:58');
/*!40000 ALTER TABLE `ai_assessment_status` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ai_assessments`
--

DROP TABLE IF EXISTS `ai_assessments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ai_assessments` (
  `assessment_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) NOT NULL,
  `risk_score` float NOT NULL,
  `risk_level` enum('LOW','MEDIUM','HIGH') NOT NULL,
  `risk_factors` json DEFAULT NULL,
  `model_version` varchar(30) DEFAULT NULL,
  `assessed_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`assessment_id`),
  UNIQUE KEY `uq_ai_assessment_request` (`request_id`),
  CONSTRAINT `fk_ai_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`),
  CONSTRAINT `chk_risk_score` CHECK (((`risk_score` >= 0) and (`risk_score` <= 100)))
) ENGINE=InnoDB AUTO_INCREMENT=43 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ai_assessments`
--

LOCK TABLES `ai_assessments` WRITE;
/*!40000 ALTER TABLE `ai_assessments` DISABLE KEYS */;
INSERT INTO `ai_assessments` VALUES (1,'REQ7EF41FFC0714',67.62,'MEDIUM','[\"New device detected\", \"Multiple failed login attempts\", \"MFA not verified\", \"Frequent phone changes\"]','1.0','2026-09-03 06:53:39'),(2,'REQB8EDEFD46374',58.45,'MEDIUM','[\"New device detected\", \"Unusual location deviation\"]','1.0','2026-09-03 07:10:38'),(3,'REQD692C7BD71F3',73.97,'MEDIUM','[\"New device detected\", \"Unusual location deviation\", \"Unusual login time pattern\"]','1.0','2026-09-03 12:39:13'),(4,'REQFD32AC2F7606',87.83,'HIGH','[\"New device detected\", \"Unusual location deviation\", \"Recent password reset\", \"Unusual login time pattern\", \"Low trust score\"]','1.0','2026-09-03 12:45:02'),(5,'REQ006C998AC733',96.16,'HIGH','[\"Unusual location deviation\", \"Multiple failed login attempts\", \"Unusual login time pattern\", \"Low trust score\"]','1.0','2026-09-03 12:59:23'),(6,'REQEB1881FB73BA',22.25,'LOW','[\"New device detected\", \"Multiple failed login attempts\", \"MFA not verified\"]','1.0','2026-09-03 13:01:55'),(7,'REQ9599BA3BB734',95.09,'HIGH','[\"New device detected\", \"Unusual location deviation\", \"Multiple failed login attempts\", \"Recent password reset\", \"MFA not verified\", \"Unusual login time pattern\"]','1.0','2026-09-03 13:03:08'),(8,'REQA7E2B5BAD079',37.95,'LOW','[\"New device detected\", \"Multiple failed login attempts\", \"Recent password reset\", \"MFA not verified\"]','1.0','2026-09-03 13:04:40'),(9,'REQD3CD604E99D4',97.26,'HIGH','[\"New device detected\", \"Unusual location deviation\", \"Multiple failed login attempts\", \"Recent password reset\", \"Unusual login time pattern\", \"Low trust score\"]','1.0','2026-09-03 13:10:46'),(10,'REQ2945DF1AA2C4',84.54,'HIGH','[\"New device detected\", \"Recent password reset\", \"MFA not verified\", \"Unusual login time pattern\"]','1.0','2026-09-08 06:04:02'),(11,'REQD41AE20C31AE',92.16,'HIGH','[\"Unusual location deviation\", \"MFA not verified\", \"Low trust score\"]','1.0','2026-09-08 06:56:28'),(12,'REQ8324168BCF8F',80.25,'HIGH','[\"Multiple failed login attempts\", \"Frequent phone changes\", \"Unusual login time pattern\", \"Low trust score\"]','1.0','2026-09-08 11:02:13'),(13,'REQ928CB6C9B30B',97.78,'HIGH','[\"Frequent phone changes\"]','1.0','2026-09-08 13:48:55'),(14,'REQ0146E2A22791',20,'LOW','[\"Frequent phone changes\"]','trust-derived-v1','2026-09-08 14:06:33'),(15,'REQ805E5ED58968',8.99,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-11 03:06:05'),(16,'REQA0292B0FCBC5',8.99,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-11 03:19:01'),(17,'REQEF4134DA86D4',8.99,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-11 03:22:52'),(18,'REQ815E65BBAF9A',8.99,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-29 12:05:57'),(19,'REQB6119CDA0E73',8.34,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 06:19:41'),(20,'REQ295D5C5BFC1E',7.74,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 06:36:25'),(21,'REQF5BC1D52BCA7',8.77,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 07:05:02'),(22,'REQ69BF6FE33FCC',11.6,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 07:41:21'),(23,'REQ4677CBE80056',16.31,'LOW','[\"MFA not verified\", \"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 08:13:03'),(24,'REQC9ABAF3F6069',11.65,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 08:15:58'),(25,'REQCD15442A58DA',16.78,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-09-30 11:37:53'),(26,'REQC010F284F7DE',48.8,'LOW','[\"Frequent phone changes\", \"Unusual login time pattern\"]','logistic-regression-v1','2026-09-30 17:16:53'),(27,'REQ5E6F50F02E4F',34.09,'LOW','[\"Frequent phone changes\", \"Unusual login time pattern\"]','logistic-regression-v1','2026-09-30 17:58:40'),(28,'REQ0484098965B8',90.9,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 02:20:13'),(29,'REQFC138A060217',8.14,'LOW','[\"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 06:06:46'),(30,'REQ38C25A2841B7',88.83,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 06:24:26'),(31,'REQ81129ACA8681',87.77,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 07:52:18'),(32,'REQ2023160632D8',87.45,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 08:01:09'),(33,'REQ6C42A94671F5',87.36,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 08:24:47'),(34,'REQ017CD25D0127',87.35,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 08:27:40'),(35,'REQ5554E1D036DE',87.64,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 08:54:35'),(36,'REQ3FA423792F56',87.77,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 09:02:53'),(37,'REQC6B806B7BF8B',87.77,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-05 09:02:54'),(38,'REQ138257FB57B3',93.49,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\", \"Unusual login time pattern\"]','logistic-regression-v1','2026-10-05 16:31:54'),(39,'REQ0127EBD0BD52',93.51,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\", \"Unusual login time pattern\"]','logistic-regression-v1','2026-10-22 13:14:58'),(40,'REQB06493A25278',87.29,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-06 08:16:58'),(41,'REQE6109612C6A9',91.01,'HIGH','[\"Unusual location deviation\", \"Frequent phone changes\"]','logistic-regression-v1','2026-10-16 12:48:27');
/*!40000 ALTER TABLE `ai_assessments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `audit_logs`
--

DROP TABLE IF EXISTS `audit_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_logs` (
  `log_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) DEFAULT NULL,
  `user_id` varchar(20) DEFAULT NULL,
  `actor` varchar(20) NOT NULL,
  `action` varchar(50) NOT NULL,
  `details` json DEFAULT NULL,
  `timestamp` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`log_id`),
  KEY `fk_audit_request` (`request_id`),
  KEY `fk_audit_user` (`user_id`),
  CONSTRAINT `fk_audit_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`),
  CONSTRAINT `fk_audit_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=95 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `audit_logs`
--

LOCK TABLES `audit_logs` WRITE;
/*!40000 ALTER TABLE `audit_logs` DISABLE KEYS */;
INSERT INTO `audit_logs` VALUES (1,'REQ7856537A998B','S1024','Mentor','MENTOR_APPROVED','{\"reason\": null, \"mentor_id\": \"M021\"}','2026-09-02 12:39:43'),(2,'REQ999TEST01','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-02 16:43:10'),(3,'REQD3CD604E99D4','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-03 13:11:07'),(4,'REQD3CD604E99D4','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-03 13:11:44'),(5,'REQ2945DF1AA2C4','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-08 06:04:18'),(6,'REQD41AE20C31AE','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-08 06:56:46'),(7,'REQD41AE20C31AE','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-08 07:00:51'),(8,'REQ2945DF1AA2C4','S1024','Mentor','MENTOR_REJECTED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-08 07:01:20'),(9,'REQD3CD604E99D4','S1024','Mentor','MENTOR_REJECTED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-08 07:01:29'),(10,'REQ8324168BCF8F','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-08 11:02:29'),(11,'REQ928CB6C9B30B','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-08 13:49:14'),(12,'REQ0146E2A22791','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-08 14:06:51'),(13,'REQ805E5ED58968','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-11 03:06:21'),(14,'REQA0292B0FCBC5','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-11 03:19:15'),(15,'REQEF4134DA86D4','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-11 03:23:03'),(16,'REQ815E65BBAF9A','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-29 12:06:08'),(17,'REQ815E65BBAF9A','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-29 12:07:03'),(18,'REQB6119CDA0E73','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 06:20:34'),(19,'REQB6119CDA0E73','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-30 06:22:39'),(20,'REQ295D5C5BFC1E','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 06:36:43'),(21,'REQ295D5C5BFC1E','S1024','Mentor','MENTOR_REJECTED','{\"reason\": \"Please dont change phone number frequently\", \"mentor_id\": \"M021\"}','2026-09-30 06:37:39'),(22,'REQF5BC1D52BCA7','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 07:05:16'),(23,'REQ69BF6FE33FCC','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 07:41:36'),(24,'REQ4677CBE80056','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 08:13:18'),(25,'REQC9ABAF3F6069','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 08:16:08'),(26,'REQCD15442A58DA','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 11:38:10'),(27,'REQCD15442A58DA','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-30 11:39:11'),(28,'REQC010F284F7DE','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 17:17:15'),(29,'REQC010F284F7DE','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-09-30 17:19:41'),(30,'REQ5E6F50F02E4F','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-09-30 17:59:10'),(31,'REQ0484098965B8','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-10-05 02:20:29'),(32,'REQFC138A060217','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-10-05 06:07:05'),(33,'REQ38C25A2841B7','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-10-05 06:25:00'),(34,'REQ017CD25D0127','S1024','Parent','PARENT_APPROVED','{\"student_name\": \"Rahul\"}','2026-10-05 08:32:34'),(35,'REQ5554E1D036DE','S1024','Parent','PARENT_APPROVED','{\"student_name\": \"Rahul\"}','2026-10-05 08:54:58'),(36,'REQC6B806B7BF8B','S1024','Parent','PARENT_APPROVED','{\"student_name\": \"Rahul\"}','2026-10-05 09:06:20'),(37,'REQC6B806B7BF8B','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-10-05 09:06:34'),(38,'REQC6B806B7BF8B','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\", \"parent_verification_status\": \"APPROVED\"}','2026-10-05 09:07:08'),(39,'REQ138257FB57B3','S1024','Parent','PARENT_DENIED','{\"student_name\": \"Rahul\"}','2026-10-05 16:33:32'),(40,'REQ0127EBD0BD52','S1024','Parent','PARENT_APPROVED','{\"student_name\": \"Rahul\"}','2026-10-05 16:40:27'),(41,'REQ0127EBD0BD52','S1024','Student','AUTHENTICATION_SUCCESS','{}','2026-10-05 16:42:20'),(42,'REQ569A4CD37860','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+21 ******2313\", \"old_phone_masked\": \"+99 ******9898\"}','2026-10-16 12:26:10'),(43,'REQ569A4CD37860','S1024','System','SMS_OTP_SENT','{}','2026-10-16 12:26:14'),(44,'REQ569A4CD37860','S1024','System','EMAIL_OTP_SENT','{}','2026-10-16 12:26:14'),(45,'REQ48D469F53343','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+24 ******2424\", \"old_phone_masked\": \"+99 ******9898\"}','2026-10-16 12:27:06'),(46,'REQ48D469F53343','S1024','System','SMS_OTP_SENT','{}','2026-10-16 12:27:10'),(47,'REQ48D469F53343','S1024','System','EMAIL_OTP_SENT','{}','2026-10-16 12:27:10'),(48,'REQ4CD6A4C2D582','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+94 ******3853\", \"old_phone_masked\": \"+99 ******9898\"}','2026-10-16 12:37:20'),(49,'REQ4CD6A4C2D582','S1024','System','SMS_OTP_SENT','{}','2026-10-16 12:37:24'),(50,'REQ4CD6A4C2D582','S1024','System','EMAIL_OTP_SENT','{}','2026-10-16 12:37:24'),(51,'REQ4CD6A4C2D582','S1024','Parent','SMS_OTP_VERIFIED','{}','2026-10-16 12:39:11'),(55,'REQ5239BB84F0F3','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+42 ******2424\", \"old_phone_masked\": \"+99 ******9898\"}','2026-10-16 12:43:43'),(56,'REQ5239BB84F0F3','S1024','System','SMS_OTP_SENT','{}','2026-10-16 12:43:47'),(57,'REQ5239BB84F0F3','S1024','System','EMAIL_OTP_SENT','{}','2026-10-16 12:43:47'),(58,'REQE6109612C6A9','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+78 ******8909\", \"old_phone_masked\": \"+99 ******9898\"}','2026-10-16 12:46:46'),(59,'REQE6109612C6A9','S1024','System','SMS_OTP_SENT','{}','2026-10-16 12:46:51'),(60,'REQE6109612C6A9','S1024','System','EMAIL_OTP_SENT','{}','2026-10-16 12:46:51'),(61,'REQE6109612C6A9','S1024','Parent','SMS_OTP_VERIFIED','{}','2026-10-16 12:48:26'),(62,'REQE6109612C6A9','S1024','Parent','EMAIL_OTP_VERIFIED','{}','2026-10-16 12:48:27'),(63,'REQE6109612C6A9','S1024','System','PARENT_AUTHENTICATION_COMPLETED','{}','2026-10-16 12:48:27'),(64,'REQE6109612C6A9','S1024','System','AI_ASSESSMENT_GENERATED','{\"risk_level\": \"HIGH\", \"risk_score\": 91.01, \"model_version\": \"logistic-regression-v1\"}','2026-10-16 12:48:27'),(65,'REQE6109612C6A9','S1024','Mentor','MENTOR_APPROVED','{\"reason\": \"\", \"mentor_id\": \"M021\"}','2026-10-16 12:52:35'),(66,'REQE6109612C6A9','S1024','System','PHONE_NUMBER_UPDATED','{\"new_phone_masked\": \"+78 ******8909\"}','2026-10-16 12:52:35'),(67,NULL,'24STUCHH010221','System','ACCOUNT_ACTIVATION_CODE_SENT','{}','2026-10-19 16:59:21'),(68,NULL,'24STUCHH010221','System','ACCOUNT_ACTIVATED','{}','2026-10-19 16:59:22'),(69,NULL,'24STUCHH011270','Admin','MENTOR_ASSIGNED','{\"admin_id\": \"ADM32430661\", \"mentor_id\": \"M045\"}','2026-10-19 17:05:32'),(70,NULL,'24STUCHH010221','Admin','MENTOR_ASSIGNED','{\"admin_id\": \"ADM32430661\", \"mentor_id\": \"M067\"}','2026-10-19 17:05:32'),(71,NULL,'24STUCHH011270','Admin','MENTOR_UNASSIGNED','{\"admin_id\": \"ADM32430661\"}','2026-10-19 17:05:32'),(72,NULL,'24STUCHH010221','Admin','MENTOR_ASSIGNED','{\"admin_id\": \"ADM32430661\", \"mentor_id\": \"M021\"}','2026-10-19 17:05:32'),(73,NULL,'24STUCHH010238','System','ACCOUNT_ACTIVATION_CODE_SENT','{}','2026-10-20 05:38:49'),(74,NULL,'24STUCHH010238','System','ACCOUNT_ACTIVATED','{}','2026-10-20 05:41:35'),(75,'REQFF8A86B8AFFC','24STUCHH010238','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+97 ******8998\", \"old_phone_masked\": \"+90 ******0002\"}','2026-10-20 05:47:37'),(76,'REQFF8A86B8AFFC','24STUCHH010238','System','SMS_OTP_SENT','{}','2026-10-20 05:47:42'),(77,'REQFF8A86B8AFFC','24STUCHH010238','System','EMAIL_OTP_SENT','{}','2026-10-20 05:47:42'),(78,'REQFF8A86B8AFFC','24STUCHH010238','Student','PHONE_CHANGE_CANCELLED','{}','2026-10-20 06:16:13'),(79,'REQ515CB0C41A46','24STUCHH010238','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+78 ******9999\", \"old_phone_masked\": \"+90 ******0002\"}','2026-10-20 06:17:04'),(80,'REQ515CB0C41A46','24STUCHH010238','System','SMS_OTP_SENT','{}','2026-10-20 06:17:08'),(81,'REQ515CB0C41A46','24STUCHH010238','System','EMAIL_OTP_SENT','{}','2026-10-20 06:17:08'),(82,'REQ515CB0C41A46','24STUCHH010238','Parent','EMAIL_OTP_VERIFIED','{}','2026-10-20 06:18:18'),(83,'REQ515CB0C41A46','24STUCHH010238','Parent','SMS_OTP_FAILED','{\"attempts\": 1}','2026-10-20 06:18:57'),(84,'REQ515CB0C41A46','24STUCHH010238','Parent','SMS_OTP_FAILED','{\"attempts\": 2}','2026-10-20 06:20:30'),(85,'REQ515CB0C41A46','24STUCHH010238','Student','PHONE_CHANGE_CANCELLED','{}','2026-10-20 06:26:24'),(86,'REQAD6B502B330E','24STUCHH010238','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+66 ******8787\", \"old_phone_masked\": \"+90 ******0002\"}','2026-10-20 06:26:35'),(87,'REQAD6B502B330E','24STUCHH010238','System','SMS_OTP_SENT','{}','2026-10-20 06:26:40'),(88,'REQAD6B502B330E','24STUCHH010238','System','EMAIL_OTP_SENT','{}','2026-10-20 06:26:40'),(89,'REQ0127EBD0BD52','S1024','System','AI_ASSESSMENT_RETRY_UNCHANGED','{\"risk_level\": \"HIGH\", \"risk_score\": 93.51, \"model_version\": \"logistic-regression-v1\", \"indicator_count\": 3, \"indicator_severity\": \"warning\"}','2026-10-22 13:14:58'),(90,'REQF95094740653','S1024','Student','PHONE_CHANGE_REQUESTED','{\"new_phone_masked\": \"+91 ******8198\", \"old_phone_masked\": \"+78 ******8909\"}','2026-10-28 14:19:25'),(91,'REQF95094740653','S1024','System','SMS_OTP_SENT','{}','2026-10-28 14:19:29'),(92,'REQF95094740653','S1024','System','EMAIL_OTP_SENT','{}','2026-10-28 14:19:29'),(93,'REQF95094740653','S1024','Student','PHONE_CHANGE_CANCELLED','{}','2026-10-29 08:10:49'),(94,'REQF95094740653','S1024','Student','REQUEST_DELETED_BY_STUDENT','{\"previous_status\": \"CANCELLED\"}','2026-10-29 08:10:56');
/*!40000 ALTER TABLE `audit_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `mentor_assignments`
--

DROP TABLE IF EXISTS `mentor_assignments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mentor_assignments` (
  `assignment_id` int NOT NULL AUTO_INCREMENT,
  `student_id` varchar(20) NOT NULL,
  `mentor_id` varchar(20) NOT NULL,
  `assigned_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`assignment_id`),
  UNIQUE KEY `uq_assignment_student` (`student_id`),
  KEY `idx_assignment_mentor` (`mentor_id`),
  CONSTRAINT `fk_assignment_mentor` FOREIGN KEY (`mentor_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_assignment_student` FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `mentor_assignments`
--

LOCK TABLES `mentor_assignments` WRITE;
/*!40000 ALTER TABLE `mentor_assignments` DISABLE KEYS */;
INSERT INTO `mentor_assignments` VALUES (1,'S1024','M021','2026-10-19 22:10:57',1),(2,'S1045','M021','2026-10-19 22:10:57',1),(3,'S2024','M021','2026-10-19 22:10:57',1),(4,'24STUCHH010221','M021','2026-10-19 22:24:24',1),(5,'24STUCHH010238','M021','2026-10-19 22:24:24',1),(6,'24STUCHH010244','M021','2026-10-19 22:24:24',1),(7,'24STUCHH010257','M021','2026-10-19 22:24:24',1),(8,'24STUCHH010263','M045','2026-10-19 22:24:24',1),(9,'24STUCHH010276','M045','2026-10-19 22:24:24',1),(10,'24STUCHH010282','M045','2026-10-19 22:24:24',1),(11,'24STUCHH010295','M045','2026-10-19 22:24:24',1),(12,'24STUCHH010301','M067','2026-10-19 22:24:24',1),(13,'24STUCHH010318','M067','2026-10-19 22:24:24',1),(14,'24STUCHH010324','M067','2026-10-19 22:24:24',1),(15,'24STUCHH010337','M067','2026-10-19 22:24:24',1),(16,'24STUCHH010343','M021','2026-10-19 22:24:24',1),(17,'24STUCHH011384','M045','2026-10-19 22:24:24',1),(18,'24STUCHH011270','M045','2026-10-19 22:35:32',0);
/*!40000 ALTER TABLE `mentor_assignments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `mentor_reviews`
--

DROP TABLE IF EXISTS `mentor_reviews`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mentor_reviews` (
  `review_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) NOT NULL,
  `mentor_id` varchar(20) NOT NULL,
  `decision` enum('APPROVED','REJECTED') NOT NULL,
  `reason` text,
  `reviewed_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`review_id`),
  KEY `fk_mentor_request` (`request_id`),
  CONSTRAINT `fk_mentor_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `mentor_reviews`
--

LOCK TABLES `mentor_reviews` WRITE;
/*!40000 ALTER TABLE `mentor_reviews` DISABLE KEYS */;
INSERT INTO `mentor_reviews` VALUES (1,'REQ7856537A998B','M021','APPROVED',NULL,'2026-09-02 12:39:43'),(2,'REQD41AE20C31AE','M021','APPROVED','','2026-09-08 07:00:51'),(3,'REQ2945DF1AA2C4','M021','REJECTED','','2026-09-08 07:01:20'),(4,'REQD3CD604E99D4','M021','REJECTED','','2026-09-08 07:01:29'),(5,'REQ815E65BBAF9A','M021','APPROVED','','2026-09-29 12:07:03'),(6,'REQB6119CDA0E73','M021','APPROVED','','2026-09-30 06:22:39'),(7,'REQ295D5C5BFC1E','M021','REJECTED','Please dont change phone number frequently','2026-09-30 06:37:39'),(8,'REQCD15442A58DA','M021','APPROVED','','2026-09-30 11:39:11'),(9,'REQC010F284F7DE','M021','APPROVED','','2026-09-30 17:19:41'),(10,'REQC6B806B7BF8B','M021','APPROVED','','2026-10-05 09:07:08'),(11,'REQE6109612C6A9','M021','APPROVED','','2026-10-16 12:52:35');
/*!40000 ALTER TABLE `mentor_reviews` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `model_evaluations`
--

DROP TABLE IF EXISTS `model_evaluations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_evaluations` (
  `evaluation_id` int NOT NULL AUTO_INCREMENT,
  `model_version` varchar(40) NOT NULL,
  `dataset_name` varchar(120) NOT NULL,
  `evaluated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `test_samples` int NOT NULL DEFAULT '0',
  `test_users` int NOT NULL DEFAULT '0',
  `train_samples` int NOT NULL DEFAULT '0',
  `train_users` int NOT NULL DEFAULT '0',
  `user_overlap` int NOT NULL DEFAULT '0',
  `accuracy` float NOT NULL DEFAULT '0',
  `precision_score` float NOT NULL DEFAULT '0',
  `recall_score` float NOT NULL DEFAULT '0',
  `f1` float NOT NULL DEFAULT '0',
  `roc_auc` float NOT NULL DEFAULT '0',
  `confusion_json` json DEFAULT NULL,
  `threshold_json` json DEFAULT NULL,
  `notes` text,
  PRIMARY KEY (`evaluation_id`),
  KEY `idx_evaluation_model` (`model_version`),
  KEY `idx_evaluation_time` (`evaluated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `model_evaluations`
--

LOCK TABLES `model_evaluations` WRITE;
/*!40000 ALTER TABLE `model_evaluations` DISABLE KEYS */;
/*!40000 ALTER TABLE `model_evaluations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `model_predictions`
--

DROP TABLE IF EXISTS `model_predictions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_predictions` (
  `prediction_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) NOT NULL,
  `user_id` varchar(20) DEFAULT NULL,
  `model_version` varchar(40) NOT NULL,
  `risk_score` float NOT NULL,
  `risk_level` varchar(10) NOT NULL,
  `latency_ms` float NOT NULL DEFAULT '0',
  `feature_values` json DEFAULT NULL,
  `predicted_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`prediction_id`),
  UNIQUE KEY `uq_prediction_request` (`request_id`),
  KEY `idx_prediction_model` (`model_version`),
  KEY `idx_prediction_time` (`predicted_at`),
  CONSTRAINT `fk_prediction_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `model_predictions`
--

LOCK TABLES `model_predictions` WRITE;
/*!40000 ALTER TABLE `model_predictions` DISABLE KEYS */;
/*!40000 ALTER TABLE `model_predictions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `model_registry`
--

DROP TABLE IF EXISTS `model_registry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `model_registry` (
  `model_id` int NOT NULL AUTO_INCREMENT,
  `model_version` varchar(40) NOT NULL,
  `model_type` varchar(40) NOT NULL,
  `status` enum('active','retired','archived') NOT NULL DEFAULT 'active',
  `artifact_hash` char(64) DEFAULT NULL,
  `feature_list` json DEFAULT NULL,
  `risk_threshold` float NOT NULL DEFAULT '50',
  `dataset_name` varchar(120) DEFAULT NULL,
  `trained_at` datetime DEFAULT NULL,
  `registered_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `notes` text,
  PRIMARY KEY (`model_id`),
  UNIQUE KEY `uq_model_version` (`model_version`),
  KEY `idx_model_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `model_registry`
--

LOCK TABLES `model_registry` WRITE;
/*!40000 ALTER TABLE `model_registry` DISABLE KEYS */;
/*!40000 ALTER TABLE `model_registry` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `notification_deliveries`
--

DROP TABLE IF EXISTS `notification_deliveries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notification_deliveries` (
  `delivery_id` bigint NOT NULL AUTO_INCREMENT,
  `notification_id` bigint NOT NULL,
  `channel` enum('email','webhook') NOT NULL,
  `status` enum('pending','delivered','failed','skipped') NOT NULL DEFAULT 'pending',
  `error_message` varchar(500) DEFAULT NULL,
  `delivered_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`delivery_id`),
  KEY `idx_delivery_notification` (`notification_id`),
  KEY `idx_delivery_status` (`status`),
  CONSTRAINT `fk_delivery_notification` FOREIGN KEY (`notification_id`) REFERENCES `notifications` (`notification_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notification_deliveries`
--

LOCK TABLES `notification_deliveries` WRITE;
/*!40000 ALTER TABLE `notification_deliveries` DISABLE KEYS */;
/*!40000 ALTER TABLE `notification_deliveries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `notifications`
--

DROP TABLE IF EXISTS `notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notifications` (
  `notification_id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` varchar(20) NOT NULL,
  `type` varchar(40) NOT NULL,
  `request_id` varchar(30) DEFAULT NULL,
  `message` varchar(500) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `read_at` timestamp NULL DEFAULT NULL,
  `delivery_status` varchar(20) NOT NULL DEFAULT 'not_requested',
  `delivery_channel` varchar(20) DEFAULT NULL,
  `delivery_error` varchar(500) DEFAULT NULL,
  `delivered_at` datetime DEFAULT NULL,
  PRIMARY KEY (`notification_id`),
  KEY `idx_notifications_user` (`user_id`),
  KEY `idx_notifications_user_unread` (`user_id`,`read_at`),
  KEY `fk_notifications_request` (`request_id`),
  CONSTRAINT `fk_notifications_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notifications_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notifications`
--

LOCK TABLES `notifications` WRITE;
/*!40000 ALTER TABLE `notifications` DISABLE KEYS */;
/*!40000 ALTER TABLE `notifications` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `phone_change_otps`
--

DROP TABLE IF EXISTS `phone_change_otps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `phone_change_otps` (
  `otp_id` int NOT NULL AUTO_INCREMENT,
  `request_id` varchar(20) NOT NULL,
  `channel` enum('SMS','EMAIL') NOT NULL,
  `code_hash` char(64) DEFAULT NULL,
  `expires_at` datetime NOT NULL,
  `attempts` int NOT NULL DEFAULT '0',
  `max_attempts` int NOT NULL DEFAULT '3',
  `locked` tinyint(1) NOT NULL DEFAULT '0',
  `verified` tinyint(1) NOT NULL DEFAULT '0',
  `verified_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`otp_id`),
  UNIQUE KEY `uq_request_channel` (`request_id`,`channel`),
  CONSTRAINT `fk_phone_change_otps_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `phone_change_otps`
--

LOCK TABLES `phone_change_otps` WRITE;
/*!40000 ALTER TABLE `phone_change_otps` DISABLE KEYS */;
INSERT INTO `phone_change_otps` VALUES (1,'REQ569A4CD37860','SMS','9122398db5d2dbb35a462e89a99b9441693ab713a42fde638bfb81600e5fe6d5','2026-10-16 18:01:10',0,3,0,0,NULL,'2026-10-16 17:56:10'),(2,'REQ569A4CD37860','EMAIL','0f909bb08e0eebbac9c07385e5e7bcc81cebcceeb2e88027f592f1ec6ec4e3c0','2026-10-16 18:01:10',0,3,0,0,NULL,'2026-10-16 17:56:10'),(3,'REQ48D469F53343','SMS','18f1bd727f816be9a5bf180888e226505e5af6f3a7da12befac8b0df0fee96cd','2026-10-16 18:02:06',0,3,0,0,NULL,'2026-10-16 17:57:06'),(4,'REQ48D469F53343','EMAIL','f421770daa05029a9df8a31ba719737f3f0e62c3decc6bacf13f78b293f20711','2026-10-16 18:02:06',0,3,0,0,NULL,'2026-10-16 17:57:06'),(5,'REQ4CD6A4C2D582','SMS',NULL,'2026-10-16 18:22:20',0,3,0,1,'2026-10-16 18:09:11','2026-10-16 18:07:20'),(6,'REQ4CD6A4C2D582','EMAIL','83d5305a819bfe8ec6c27422b71aea8ee0a7b98ca5c2b5325d8227bbf08464e9','2026-10-16 18:22:20',0,3,0,0,NULL,'2026-10-16 18:07:20'),(7,'REQ5239BB84F0F3','SMS','b8bb51b5b1ea9a459b80fdf950744408be2818a51e1c8285c67e45f77b17dcaa','2026-10-16 18:28:43',0,3,0,0,NULL,'2026-10-16 18:13:43'),(8,'REQ5239BB84F0F3','EMAIL','c83f6664e89cd2e94827a228cb82be06fbfaab45c6188c635927b008ab27c286','2026-10-16 18:28:43',0,3,0,0,NULL,'2026-10-16 18:13:43'),(9,'REQE6109612C6A9','SMS',NULL,'2026-10-16 18:31:46',0,3,0,1,'2026-10-16 18:18:26','2026-10-16 18:16:46'),(10,'REQE6109612C6A9','EMAIL',NULL,'2026-10-16 18:31:46',0,3,0,1,'2026-10-16 18:18:27','2026-10-16 18:16:46'),(11,'REQFF8A86B8AFFC','SMS',NULL,'2026-10-20 11:22:37',0,3,1,0,NULL,'2026-10-20 11:17:37'),(12,'REQFF8A86B8AFFC','EMAIL',NULL,'2026-10-20 11:22:37',0,3,1,0,NULL,'2026-10-20 11:17:37'),(13,'REQ515CB0C41A46','SMS',NULL,'2026-10-20 11:52:04',2,3,1,0,NULL,'2026-10-20 11:47:04'),(14,'REQ515CB0C41A46','EMAIL',NULL,'2026-10-20 11:52:04',0,3,0,1,'2026-10-20 11:48:18','2026-10-20 11:47:04'),(15,'REQAD6B502B330E','SMS','2a563c4ee4faec32da187f979ee7c66a0b96d562eb7261807f6c68f15af103a1','2026-10-20 12:01:35',0,3,0,0,NULL,'2026-10-20 11:56:35'),(16,'REQAD6B502B330E','EMAIL','03e9d15a1c13901770ac8ab40a2c511ce16624b7502233e606517164ec78a72a','2026-10-20 12:01:35',0,3,0,0,NULL,'2026-10-20 11:56:35'),(17,'REQF95094740653','SMS',NULL,'2026-10-28 19:54:25',0,3,1,0,NULL,'2026-10-28 19:49:25'),(18,'REQF95094740653','EMAIL',NULL,'2026-10-28 19:54:25',0,3,1,0,NULL,'2026-10-28 19:49:25');
/*!40000 ALTER TABLE `phone_change_otps` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `phone_change_requests`
--

DROP TABLE IF EXISTS `phone_change_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `phone_change_requests` (
  `request_id` varchar(30) NOT NULL,
  `user_id` varchar(20) NOT NULL,
  `old_phone` varchar(15) NOT NULL,
  `new_phone` varchar(15) NOT NULL,
  `requested_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `auth_status` enum('PENDING','VERIFIED','FAILED') NOT NULL DEFAULT 'PENDING',
  `parent_verification_status` varchar(20) NOT NULL DEFAULT 'PENDING',
  `parent_verified_at` timestamp NULL DEFAULT NULL,
  `parent_token_hash` varchar(64) DEFAULT NULL,
  `parent_token_expires_at` timestamp NULL DEFAULT NULL,
  `status` varchar(30) NOT NULL DEFAULT 'PENDING',
  `mentor_id` varchar(20) DEFAULT NULL,
  `reviewed_at` timestamp NULL DEFAULT NULL,
  `rejection_reason` text,
  `deleted_by_student` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`request_id`),
  KEY `fk_phone_request_user` (`user_id`),
  CONSTRAINT `fk_phone_request_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `phone_change_requests`
--

LOCK TABLES `phone_change_requests` WRITE;
/*!40000 ALTER TABLE `phone_change_requests` DISABLE KEYS */;
INSERT INTO `phone_change_requests` VALUES ('REQ006C998AC733','S1024','9112233445','+91 98765 43211','2026-09-03 12:59:23','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ0127EBD0BD52','S1024','9999989898','3636363683','2026-10-05 16:35:35','VERIFIED','APPROVED','2026-10-05 16:40:27',NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ0146E2A22791','S1024','9112233448','9192233448','2026-09-08 14:06:33','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ017CD25D0127','S1024','1235888565','9385935938','2026-10-05 08:27:40','PENDING','APPROVED','2026-10-05 08:32:34',NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ0484098965B8','S1024','1235888565','7989898988','2026-10-05 02:20:13','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ138257FB57B3','S1024','9999989898','1212121210','2026-10-05 16:31:54','PENDING','DENIED',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ2023160632D8','S1024','1235888565','6464648990','2026-10-05 08:01:09','PENDING','PENDING',NULL,'66d2dc82ca2f44d8f2255c40742a4acf2480f96d9ea920a5892b3310f059e88b','2026-10-05 08:31:09','CANCELLED','M021',NULL,NULL,0),('REQ2945DF1AA2C4','S1024','9112233445','+91 98765 43219','2026-09-08 06:04:01','VERIFIED','PENDING',NULL,NULL,NULL,'REJECTED','M021','2026-09-08 07:01:20','',0),('REQ295D5C5BFC1E','S1024','8999999987','6925696993','2026-09-30 06:36:25','VERIFIED','PENDING',NULL,NULL,NULL,'REJECTED','M021','2026-09-30 06:37:39','Please dont change phone number frequently',0),('REQ38C25A2841B7','S1024','1235888565','9112233447','2026-10-05 06:24:26','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ3FA423792F56','S1024','1235888565','9999989898','2026-10-05 09:02:53','PENDING','PENDING',NULL,'b8a547a5b18183412e1c187bd35762d5b989e915d55e77a03613b25a6b6009d5','2026-10-05 09:32:53','CANCELLED','M021',NULL,NULL,0),('REQ4677CBE80056','S1024','8999999987','6976498614','2026-09-30 08:13:03','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ48D469F53343','S1024','9999989898','2424242424','2026-10-16 12:27:06','PENDING','PENDING',NULL,'f186290aa4c9fa3457c62efe1886d3eee0e0da65bbc80c7be19b0fd8b973af59','2026-10-16 12:42:06','CANCELLED','M021',NULL,NULL,0),('REQ4CD6A4C2D582','S1024','9999989898','9453953853','2026-10-16 12:37:20','PENDING','PENDING',NULL,'1251174318082b7ef43a0c65a5dee4661613a028412435875bb9f1d630befde9','2026-10-16 12:52:20','CANCELLED','M021',NULL,NULL,0),('REQ515CB0C41A46','24STUCHH010238','9000000002','7889999999','2026-10-20 06:17:04','PENDING','PENDING',NULL,'0685df6ba98dfad99ffca37486bfde2f710876a1d1a578eefb3e89dc1e41b144','2026-10-20 06:26:24','CANCELLED','M021',NULL,NULL,0),('REQ5239BB84F0F3','S1024','9999989898','4242242424','2026-10-16 12:43:43','PENDING','PENDING',NULL,'93e15cdecb3884660616d3e0b7235204301511c078e81a506afb904c53e70ce3','2026-10-16 12:58:43','CANCELLED','M021',NULL,NULL,0),('REQ5554E1D036DE','S1024','1235888565','4343333333','2026-10-05 08:54:35','PENDING','APPROVED','2026-10-05 08:54:58',NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ569A4CD37860','S1024','9999989898','2122132313','2026-10-16 12:26:10','PENDING','PENDING',NULL,'595555ed0871efffa629de4c6821306e2ba1699a846823f86b27447140ba399f','2026-10-16 12:41:10','CANCELLED','M021',NULL,NULL,0),('REQ5E6F50F02E4F','S1024','1235888565','6913891389','2026-09-30 17:58:40','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ69BF6FE33FCC','S1024','8999999987','8393195144','2026-09-30 07:41:21','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ6C42A94671F5','S1024','1235888565','2424445464','2026-10-05 08:24:47','PENDING','PENDING',NULL,'327cdd89db899d296e3bf459f5311f94edb241b990665bfdddd1c799dfb6c333','2026-10-05 08:54:47','CANCELLED','M021',NULL,NULL,0),('REQ7856537A998B','S1024','9876543210','9112233445','2026-09-02 12:27:26','PENDING','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-02 12:39:43',NULL,0),('REQ7EF41FFC0714','S1024','9112233445','9444555666','2026-09-03 06:53:38','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ805E5ED58968','S1024','9112233448','8999999988','2026-09-11 03:06:05','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ80E2A43D387A','S1024','9876543210','9998887777','2026-09-02 12:15:14','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED',NULL,NULL,NULL,0),('REQ81129ACA8681','S1024','1235888565','1223324555','2026-10-05 07:52:18','PENDING','PENDING',NULL,'a566776892fe623cf14c9539a17c8e1abcc944c6c94d82241c76ebd3a681e77c','2026-10-05 08:22:18','CANCELLED','M021',NULL,NULL,0),('REQ815E65BBAF9A','S1024','9112233448','22232441411','2026-09-29 12:05:57','VERIFIED','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-29 12:07:03',NULL,0),('REQ8324168BCF8F','S1024','9112233448','9112233448','2026-09-08 11:02:13','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ8F448F7C0278','S1024','9112233445','9333444555','2026-09-03 06:34:38','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ928CB6C9B30B','S1024','9112233448','9112233447','2026-09-08 13:48:55','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ9599BA3BB734','S1024','9112233445','+91 98765 43219','2026-09-03 13:03:08','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQ999TEST01','S1024','9112233445','9999111222','2026-09-02 16:41:16','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQA0292B0FCBC5','S1024','9112233448','8999999987','2026-09-11 03:19:01','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQA04CCE0448F8','S1024','9112233445','9444555666','2026-09-03 06:49:14','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQA7E2B5BAD079','S1024','9112233445','+91 98765 43218','2026-09-03 13:04:40','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQAD6B502B330E','24STUCHH010238','9000000002','6668878787','2026-10-20 06:26:35','PENDING','PENDING',NULL,'04034bdf7b81d38cebe5b99e6a02df7b195ab9a562d8a70e7dac13f8f269fce1','2026-10-20 06:41:35','PENDING','M021',NULL,NULL,0),('REQB06493A25278','S1024','9999989898','9192233448','2026-10-06 08:16:58','PENDING','PENDING',NULL,'a7a79cfb31f5ddb38981c64595bc99a929d1f4f5e5cdb055a7eeb20f338c83a5','2026-10-06 08:46:58','CANCELLED','M021',NULL,NULL,0),('REQB6119CDA0E73','S1024','22232441411','8999999987','2026-09-30 06:19:41','VERIFIED','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-30 06:22:39',NULL,0),('REQB8EDEFD46374','S1024','9112233445','9555666777','2026-09-03 07:10:38','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQC010F284F7DE','S1024','3652866999','1235888565','2026-09-30 17:16:53','VERIFIED','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-30 17:19:41',NULL,0),('REQC6B806B7BF8B','S1024','1235888565','9999989898','2026-10-05 09:02:54','VERIFIED','APPROVED','2026-10-05 09:06:20',NULL,NULL,'APPROVED','M021','2026-10-05 09:07:08',NULL,0),('REQC9ABAF3F6069','S1024','8999999987','9467913411','2026-09-30 08:15:58','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQCD15442A58DA','S1024','8999999987','3652866999','2026-09-30 11:37:53','VERIFIED','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-30 11:39:11',NULL,0),('REQD3CD604E99D4','S1024','9112233445','+91 98765 43219','2026-09-03 13:10:46','VERIFIED','PENDING',NULL,NULL,NULL,'REJECTED','M021','2026-09-08 07:01:29','',0),('REQD41AE20C31AE','S1024','9112233445','9112233448','2026-09-08 06:56:28','VERIFIED','PENDING',NULL,NULL,NULL,'APPROVED','M021','2026-09-08 07:00:51',NULL,0),('REQD692C7BD71F3','S1024','9112233445','+91 98765 43211','2026-09-03 12:39:13','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQD6C3B6EC8CC8','S1024','9112233445','9111222333','2026-09-03 05:57:31','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQE6109612C6A9','S1024','9999989898','7858588909','2026-10-16 12:46:46','VERIFIED','VERIFIED','2026-10-16 12:48:27','b0a6357e8119600846223e3c5a2fb48c85e6815b027e9a775fd387ec2c14ec2a','2026-10-16 13:01:46','APPROVED','M021','2026-10-16 12:52:35',NULL,0),('REQEB1881FB73BA','S1024','9112233445','+91 98765 43211','2026-09-03 13:01:55','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQEF4134DA86D4','S1024','9112233448','9112233446','2026-09-11 03:22:52','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQF5BC1D52BCA7','S1024','8999999987','3983171599','2026-09-30 07:05:02','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQF95094740653','S1024','7858588909','9141938198','2026-10-28 14:19:25','PENDING','PENDING',NULL,'507bdbc002706ec2707c6687b5e912239db7b93cdc14edc00760a0311fefce87','2026-10-29 08:10:49','CANCELLED','M021',NULL,NULL,1),('REQFC138A060217','S1024','1235888565','1231234590','2026-10-05 06:06:46','VERIFIED','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQFD32AC2F7606','S1024','9112233445','+91 98765 43211','2026-09-03 12:45:02','PENDING','PENDING',NULL,NULL,NULL,'CANCELLED','M021',NULL,NULL,0),('REQFF8A86B8AFFC','24STUCHH010238','9000000002','9799898998','2026-10-20 05:47:37','PENDING','PENDING',NULL,'9db7bbb16d0fd12540801e3b8618196963ab133fab3a9a1b38100b3a4dddf020','2026-10-20 06:16:13','CANCELLED','M021',NULL,NULL,0);
/*!40000 ALTER TABLE `phone_change_requests` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `request_sla_policies`
--

DROP TABLE IF EXISTS `request_sla_policies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `request_sla_policies` (
  `policy_id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(60) NOT NULL,
  `reminder_after_hours` int NOT NULL DEFAULT '24',
  `escalate_after_hours` int NOT NULL DEFAULT '72',
  `notify_admin` tinyint(1) NOT NULL DEFAULT '1',
  `enabled` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` varchar(20) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`policy_id`),
  KEY `idx_sla_enabled` (`enabled`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `request_sla_policies`
--

LOCK TABLES `request_sla_policies` WRITE;
/*!40000 ALTER TABLE `request_sla_policies` DISABLE KEYS */;
INSERT INTO `request_sla_policies` VALUES (1,'default',24,72,1,1,NULL,'2026-10-28 19:59:10','2026-10-28 19:59:10');
/*!40000 ALTER TABLE `request_sla_policies` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `request_timeline`
--

DROP TABLE IF EXISTS `request_timeline`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `request_timeline` (
  `timeline_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) NOT NULL,
  `event_type` varchar(60) NOT NULL,
  `category` enum('submitted','verification','ai','alert','decision','notification','recovery','system') NOT NULL DEFAULT 'system',
  `actor_type` enum('student','mentor','admin','parent','system') NOT NULL DEFAULT 'system',
  `actor_id` varchar(20) DEFAULT NULL,
  `title` varchar(160) NOT NULL,
  `summary` varchar(500) DEFAULT NULL,
  `details_json` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`timeline_id`),
  KEY `idx_timeline_request` (`request_id`,`created_at`),
  CONSTRAINT `fk_timeline_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `request_timeline`
--

LOCK TABLES `request_timeline` WRITE;
/*!40000 ALTER TABLE `request_timeline` DISABLE KEYS */;
/*!40000 ALTER TABLE `request_timeline` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `revoked_tokens`
--

DROP TABLE IF EXISTS `revoked_tokens`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `revoked_tokens` (
  `revocation_id` bigint NOT NULL AUTO_INCREMENT,
  `jti` varchar(64) NOT NULL,
  `user_id` varchar(20) NOT NULL,
  `revoked_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `expires_at` datetime NOT NULL,
  `reason` varchar(120) DEFAULT NULL,
  PRIMARY KEY (`revocation_id`),
  UNIQUE KEY `uq_revoked_jti` (`jti`),
  KEY `idx_revoked_user` (`user_id`),
  KEY `idx_revoked_expiry` (`expires_at`),
  CONSTRAINT `fk_revoked_token_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `revoked_tokens`
--

LOCK TABLES `revoked_tokens` WRITE;
/*!40000 ALTER TABLE `revoked_tokens` DISABLE KEYS */;
INSERT INTO `revoked_tokens` VALUES (2,'54fd78da6f744b0f810bd35d5987ba7e','S1024','2026-10-30 18:13:39','2026-10-30 19:10:56','logout'),(3,'d4d8638fb0a84cb8bf58a214ed5e2eb7','M021','2026-10-30 18:14:53','2026-10-30 19:14:20','logout'),(4,'4d1780b9d7a14f4c8c656e9afbe8c4ed','ADMBD61442F','2026-10-30 18:16:16','2026-10-30 19:15:52','logout');
/*!40000 ALTER TABLE `revoked_tokens` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `schema_migrations`
--

DROP TABLE IF EXISTS `schema_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `schema_migrations` (
  `version` varchar(20) NOT NULL,
  `name` varchar(191) NOT NULL,
  `checksum` char(64) DEFAULT NULL,
  `status` enum('applied','deferred','failed') NOT NULL DEFAULT 'applied',
  `applied_at` datetime DEFAULT NULL,
  `verified_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `applied_by` varchar(150) DEFAULT NULL,
  `notes` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `schema_migrations`
--

LOCK TABLES `schema_migrations` WRITE;
/*!40000 ALTER TABLE `schema_migrations` DISABLE KEYS */;
INSERT INTO `schema_migrations` VALUES ('001','dual_parent_otp','1bbae6b3f357080817d00b93d485da53df12adeaf995f599a848c1d719538e1c','applied',NULL,'2026-10-28 20:01:16','baseline-audit','Verified 2026-10-28; exact original apply time not recorded.'),('002','sis_onboarding','7b4b75aa8ef0d08543fdb8c675aba691ae3e72415daac53edbbf6d1b242eddfd','applied',NULL,'2026-10-28 20:01:16','baseline-audit','Verified 2026-10-28; exact original apply time not recorded.'),('003','drop_users_mentor_id',NULL,'deferred',NULL,'2026-10-28 20:01:16','baseline-audit','Intentionally not applied; destructive. See database/PHASE1_REPORT.md.'),('004','notifications_and_student_delete','6cfb2db71c8c27734b64db8c7bec89347efb3b38e8f635bcda55a310ed9423fd','applied','2026-10-28 20:01:16','2026-10-28 20:01:16','schema-audit','Applied 2026-10-28 after backup; was missing from live.'),('005','security_ops','cfc69638972a6a99c1321b26bf23e43493d7ef7fd3abfd657cbb19c447ce0a70','applied','2026-10-28 20:01:16','2026-10-28 20:01:16','schema-audit','Applied 2026-10-28 after backup; was missing from live.'),('006','ai_assessment_state_and_token_revocation','c65cfe552b4f21e26128caac89580b6fc937abd950974ca65a483d0282c56c77','applied',NULL,'2026-10-28 20:01:16','baseline-audit','Verified 2026-10-28; exact original apply time not recorded.'),('007','schema_migration_ledger',NULL,'applied','2026-10-28 20:01:16','2026-10-28 20:01:16','schema-audit','Creates this ledger. Safe to re-run.');
/*!40000 ALTER TABLE `schema_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `security_alerts`
--

DROP TABLE IF EXISTS `security_alerts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `security_alerts` (
  `alert_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) DEFAULT NULL,
  `user_id` varchar(20) DEFAULT NULL,
  `alert_type` varchar(60) NOT NULL,
  `severity` enum('info','warning','critical') NOT NULL DEFAULT 'info',
  `source` enum('system','student','mentor','admin') NOT NULL DEFAULT 'system',
  `message` varchar(500) NOT NULL,
  `indicators_json` json DEFAULT NULL,
  `status` enum('open','acknowledged','resolved') NOT NULL DEFAULT 'open',
  `raised_by` varchar(20) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `acknowledged_by` varchar(20) DEFAULT NULL,
  `acknowledged_at` datetime DEFAULT NULL,
  `resolved_by` varchar(20) DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `resolution_note` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`alert_id`),
  KEY `idx_alert_status` (`status`),
  KEY `idx_alert_request` (`request_id`),
  KEY `idx_alert_user` (`user_id`),
  CONSTRAINT `fk_alert_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `security_alerts`
--

LOCK TABLES `security_alerts` WRITE;
/*!40000 ALTER TABLE `security_alerts` DISABLE KEYS */;
/*!40000 ALTER TABLE `security_alerts` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `security_context`
--

DROP TABLE IF EXISTS `security_context`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `security_context` (
  `context_id` bigint NOT NULL AUTO_INCREMENT,
  `request_id` varchar(30) NOT NULL,
  `known_device` tinyint(1) NOT NULL,
  `location_deviation` float NOT NULL,
  `failed_login_count` int NOT NULL,
  `recent_password_reset` tinyint(1) NOT NULL,
  `mfa_verified` tinyint(1) NOT NULL,
  `phone_change_frequency` int NOT NULL,
  `login_time_deviation` float NOT NULL,
  `trust_score` float NOT NULL,
  `captured_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`context_id`),
  KEY `fk_security_request` (`request_id`),
  CONSTRAINT `fk_security_request` FOREIGN KEY (`request_id`) REFERENCES `phone_change_requests` (`request_id`),
  CONSTRAINT `chk_failed_login_count` CHECK ((`failed_login_count` >= 0)),
  CONSTRAINT `chk_location_deviation` CHECK ((`location_deviation` >= 0)),
  CONSTRAINT `chk_login_time_deviation` CHECK ((`login_time_deviation` >= 0)),
  CONSTRAINT `chk_phone_change_frequency` CHECK ((`phone_change_frequency` >= 0)),
  CONSTRAINT `chk_trust_score` CHECK ((`trust_score` >= 0))
) ENGINE=InnoDB AUTO_INCREMENT=53 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `security_context`
--

LOCK TABLES `security_context` WRITE;
/*!40000 ALTER TABLE `security_context` DISABLE KEYS */;
INSERT INTO `security_context` VALUES (1,'REQD6C3B6EC8CC8',0,0.46,4,0,0,2,0.76,79.53,'2026-09-03 05:57:31'),(2,'REQ8F448F7C0278',1,0.74,1,1,1,3,0.57,54.04,'2026-09-03 06:34:38'),(3,'REQA04CCE0448F8',0,0.91,3,0,0,0,0.63,52.45,'2026-09-03 06:49:14'),(4,'REQ7EF41FFC0714',0,0.16,4,0,0,3,0.15,54.88,'2026-09-03 06:53:38'),(5,'REQB8EDEFD46374',0,0.62,1,0,1,1,0.47,70.3,'2026-09-03 07:10:38'),(6,'REQD692C7BD71F3',0,1,0,0,1,0,0.71,75.39,'2026-09-03 12:39:13'),(7,'REQFD32AC2F7606',0,0.68,0,1,1,1,0.86,43.16,'2026-09-03 12:45:02'),(8,'REQ006C998AC733',1,0.93,5,0,1,1,0.85,39.6,'2026-09-03 12:59:23'),(9,'REQEB1881FB73BA',0,0.05,4,0,0,1,0.19,89.91,'2026-09-03 13:01:55'),(10,'REQ9599BA3BB734',0,0.8,3,1,0,2,0.67,58.26,'2026-09-03 13:03:08'),(11,'REQA7E2B5BAD079',0,0.21,3,1,0,0,0.44,80.92,'2026-09-03 13:04:40'),(12,'REQD3CD604E99D4',0,0.66,5,1,1,2,0.99,48.04,'2026-09-03 13:10:46'),(13,'REQ2945DF1AA2C4',0,0.6,0,1,0,2,0.94,77.44,'2026-09-08 06:04:02'),(14,'REQD41AE20C31AE',1,0.94,2,0,0,1,0.48,30.44,'2026-09-08 06:56:28'),(15,'REQ8324168BCF8F',1,0.21,5,0,1,3,0.61,47.84,'2026-09-08 11:02:13'),(16,'REQ928CB6C9B30B',1,0,0,0,1,18,0,80,'2026-09-08 13:48:55'),(17,'REQ0146E2A22791',1,0,0,0,1,3,0,80,'2026-09-08 14:06:33'),(18,'REQ805E5ED58968',1,0,0,0,1,3,0,81,'2026-09-11 03:06:05'),(19,'REQA0292B0FCBC5',1,0,0,0,1,3,0,81,'2026-09-11 03:19:01'),(20,'REQEF4134DA86D4',1,0,0,0,1,3,0,81,'2026-09-11 03:22:52'),(21,'REQ815E65BBAF9A',1,0,0,0,1,3,0,81,'2026-09-29 12:05:57'),(22,'REQB6119CDA0E73',1,0,0,0,1,3,0,84,'2026-09-30 06:19:41'),(23,'REQ295D5C5BFC1E',1,0,0,0,1,3,0,87,'2026-09-30 06:36:25'),(24,'REQF5BC1D52BCA7',1,0,0,0,1,3,0,82,'2026-09-30 07:05:02'),(25,'REQ69BF6FE33FCC',1,0,0,0,1,3,0,82,'2026-09-30 07:41:21'),(26,'REQ4677CBE80056',1,0,0,0,0,3,0.0014,82,'2026-09-30 08:13:03'),(27,'REQC9ABAF3F6069',1,0,0,0,1,3,0.0021,82,'2026-09-30 08:15:58'),(28,'REQCD15442A58DA',1,0,0,0,1,3,0.2054,82,'2026-09-30 11:37:53'),(29,'REQC010F284F7DE',1,0.2047,0,0,1,3,0.6132,85,'2026-09-30 17:16:53'),(30,'REQ5E6F50F02E4F',1,0.0177,0,0,1,3,0.6268,85,'2026-09-30 17:58:40'),(31,'REQ0484098965B8',1,1,0,0,1,3,0.4362,85,'2026-10-05 02:20:13'),(32,'REQFC138A060217',1,0,0,0,1,3,0,85,'2026-10-05 06:06:46'),(33,'REQ38C25A2841B7',1,1,0,0,1,3,0.3274,85,'2026-10-05 06:24:26'),(34,'REQ81129ACA8681',1,1,0,0,1,3,0.2781,85,'2026-10-05 07:52:18'),(35,'REQ2023160632D8',1,1,0,0,1,3,0.2641,85,'2026-10-05 08:01:09'),(36,'REQ6C42A94671F5',1,1,0,0,1,3,0.26,85,'2026-10-05 08:24:47'),(37,'REQ017CD25D0127',1,1,0,0,1,3,0.2598,85,'2026-10-05 08:27:40'),(38,'REQ5554E1D036DE',1,1,0,0,1,3,0.2724,85,'2026-10-05 08:54:35'),(39,'REQ3FA423792F56',1,1,0,0,1,3,0.2782,85,'2026-10-05 09:02:53'),(40,'REQC6B806B7BF8B',1,1,0,0,1,3,0.2782,85,'2026-10-05 09:02:54'),(41,'REQ138257FB57B3',1,1,0,0,1,3,0.6098,85,'2026-10-05 16:31:54'),(42,'REQ0127EBD0BD52',1,1,0,0,1,3,0.6117,85,'2026-10-05 16:35:35'),(43,'REQB06493A25278',1,1,0,0,1,3,0.2572,85,'2026-10-06 08:16:58'),(44,'REQ569A4CD37860',1,1,0,0,1,3,0.4333,85,'2026-10-16 12:26:10'),(45,'REQ48D469F53343',1,1,0,0,1,3,0.4345,85,'2026-10-16 12:27:06'),(46,'REQ4CD6A4C2D582',1,1,0,0,1,3,0.4323,85,'2026-10-16 12:37:20'),(47,'REQ5239BB84F0F3',1,1,0,0,1,3,0.4391,85,'2026-10-16 12:43:43'),(48,'REQE6109612C6A9',1,1,0,0,1,3,0.4426,85,'2026-10-16 12:46:46'),(49,'REQFF8A86B8AFFC',1,0,0,0,0,0,0,80,'2026-10-20 05:47:37'),(50,'REQ515CB0C41A46',1,1,0,0,0,1,0.0247,80,'2026-10-20 06:17:04'),(51,'REQAD6B502B330E',1,1,0,0,0,2,0.0372,80,'2026-10-20 06:26:35'),(52,'REQF95094740653',1,1,0,0,1,3,0.4656,85,'2026-10-28 14:19:25');
/*!40000 ALTER TABLE `security_context` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `security_events`
--

DROP TABLE IF EXISTS `security_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `security_events` (
  `event_id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` varchar(20) NOT NULL,
  `event_type` varchar(40) NOT NULL,
  `success` tinyint(1) NOT NULL DEFAULT '1',
  `device_id` varchar(255) DEFAULT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` text,
  `latitude` decimal(10,7) DEFAULT NULL,
  `longitude` decimal(10,7) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`event_id`),
  KEY `idx_security_user` (`user_id`),
  KEY `idx_security_user_event` (`user_id`,`event_type`),
  CONSTRAINT `fk_security_event_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=101 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `security_events`
--

LOCK TABLES `security_events` WRITE;
/*!40000 ALTER TABLE `security_events` DISABLE KEYS */;
INSERT INTO `security_events` VALUES (1,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:12:50'),(2,'S1024','MFA_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:13:18'),(3,'M021','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:13:34'),(4,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:15:52'),(5,'S1024','MFA_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:16:08'),(6,'M021','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 08:17:04'),(7,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868251,78.3601038,'2026-09-30 08:34:44'),(8,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868251,78.3601038,'2026-09-30 08:34:50'),(9,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868488,78.3600932,'2026-09-30 08:35:37'),(10,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868488,78.3600932,'2026-09-30 08:35:42'),(11,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868488,78.3600932,'2026-09-30 08:35:43'),(12,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868488,78.3600932,'2026-09-30 08:35:46'),(13,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868556,78.3600989,'2026-09-30 08:43:46'),(14,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868522,78.3601282,'2026-09-30 10:47:52'),(15,'S1024','LOGIN_SUCCESS',1,'8cc38ee5-8eb9-4a1d-b65c-5ad3afa35aae','127.0.0.1','python-requests/2.32.5',17.3868522,78.3601282,'2026-09-30 10:47:55'),(16,'S1024','LOGIN_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',17.3868503,78.3601178,'2026-09-30 11:37:33'),(17,'S1024','MFA_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 11:38:10'),(18,'M021','LOGIN_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',17.3868419,78.3601159,'2026-09-30 11:38:38'),(19,'S1024','LOGIN_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',17.3868467,78.3601179,'2026-09-30 11:40:18'),(20,'S1024','LOGIN_SUCCESS',1,'e0e0644e-7e48-4110-b6ba-f18065ee77bf','127.0.0.1','python-requests/2.32.5',17.4872877,78.1778548,'2026-09-30 17:14:47'),(21,'S1024','MFA_SUCCESS',1,'e0e0644e-7e48-4110-b6ba-f18065ee77bf','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 17:17:15'),(22,'M021','LOGIN_SUCCESS',1,'e0e0644e-7e48-4110-b6ba-f18065ee77bf','127.0.0.1','python-requests/2.32.5',17.4872875,78.1778560,'2026-09-30 17:18:12'),(23,'S1024','LOGIN_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',17.3868388,78.3601342,'2026-09-30 17:58:15'),(24,'S1024','MFA_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-09-30 17:59:10'),(25,'M021','LOGIN_SUCCESS',1,'f926ac22-15a2-4cb6-af22-b9aed2de7ec6','127.0.0.1','python-requests/2.32.5',17.3868638,78.3601356,'2026-09-30 17:59:31'),(26,'S1024','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.4191626,78.2200559,'2026-10-05 01:35:04'),(27,'S1024','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.4191629,78.2200429,'2026-10-05 02:06:55'),(28,'S1024','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.4191629,78.2200429,'2026-10-05 02:07:07'),(29,'S1024','LOGIN_SUCCESS',1,'78764267-dd64-490f-be63-059e55037205','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 02:17:40'),(30,'S1024','LOGIN_SUCCESS',1,'78764267-dd64-490f-be63-059e55037205','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 02:17:58'),(31,'S1024','LOGIN_SUCCESS',1,'84db5977-ba30-4cb8-b7fd-592a0d82dbc9','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 02:20:01'),(32,'S1024','MFA_SUCCESS',1,'84db5977-ba30-4cb8-b7fd-592a0d82dbc9','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 02:20:29'),(33,'M021','LOGIN_SUCCESS',1,'84db5977-ba30-4cb8-b7fd-592a0d82dbc9','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 02:20:50'),(34,'S1024','LOGIN_SUCCESS',1,'84db5977-ba30-4cb8-b7fd-592a0d82dbc9','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 02:26:49'),(35,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 06:23:49'),(36,'S1024','MFA_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 06:25:00'),(37,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 06:25:13'),(38,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 07:10:31'),(39,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 07:52:08'),(40,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 08:00:59'),(41,'S1024','MFA_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 09:06:34'),(42,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 09:06:48'),(43,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 09:10:43'),(44,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 09:28:43'),(45,'S1024','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.3867873,78.3601112,'2026-10-05 16:30:22'),(46,'S1024','MFA_FAILURE',0,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 16:34:12'),(47,'S1024','MFA_FAILURE',0,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 16:41:54'),(48,'S1024','MFA_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',NULL,NULL,'2026-10-05 16:42:20'),(49,'M021','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.3867873,78.3601112,'2026-10-05 16:44:16'),(50,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-05 16:51:14'),(51,'S1024','LOGIN_SUCCESS',1,'78764267-dd64-490f-be63-059e55037205','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-06 05:35:56'),(52,'S1024','LOGIN_SUCCESS',1,'78764267-dd64-490f-be63-059e55037205','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-06 05:39:54'),(53,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-06 08:14:36'),(54,'S1024','LOGIN_SUCCESS',1,'bf56e299-1608-4a1a-a34f-822fcb40dee3','127.0.0.1','python-requests/2.32.5',17.4191313,78.2199801,'2026-10-06 08:43:47'),(55,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-16 12:21:44'),(56,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-16 12:35:59'),(57,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.32.5',19.0759840,72.8776560,'2026-10-16 12:51:58'),(58,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',37.7749290,-122.4194160,'2026-10-19 13:24:42'),(59,'24STUCHH010221','LOGIN_SUCCESS',1,NULL,'127.0.0.1','Werkzeug/3.1.9',NULL,NULL,'2026-10-19 17:00:06'),(60,'24STUCHH010221','LOGIN_FAILURE',0,NULL,'127.0.0.1','Werkzeug/3.1.9',NULL,NULL,'2026-10-19 17:00:07'),(61,'ADM32430661','LOGIN_SUCCESS',1,NULL,'127.0.0.1','Werkzeug/3.1.9',NULL,NULL,'2026-10-19 17:05:31'),(62,'ADMBD61442F','LOGIN_SUCCESS',1,NULL,'127.0.0.1','Werkzeug/3.1.9',NULL,NULL,'2026-10-20 05:24:30'),(63,'ADMBD61442F','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',55.7558260,37.6173000,'2026-10-20 05:30:06'),(64,'24STUCHH010238','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',55.7558260,37.6173000,'2026-10-20 05:47:17'),(65,'ADMBD61442F','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 05:59:30'),(66,'24STUCHH010238','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 05:59:32'),(67,'ADMBD61442F','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 06:00:38'),(68,'24STUCHH010238','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 06:00:40'),(69,'ADMBD61442F','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 06:11:35'),(70,'24STUCHH010238','LOGIN_SUCCESS',1,NULL,'127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-20 06:11:36'),(71,'S1024','LOGIN_SUCCESS',1,'hc-check','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:34'),(72,'M021','LOGIN_SUCCESS',1,'hc-check','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:35'),(73,'ADMBD61442F','LOGIN_FAILURE',0,'hc-check','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:36'),(74,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:56'),(75,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:57'),(76,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:58'),(77,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:49:59'),(78,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:50:01'),(79,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:50:01'),(80,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:50:02'),(81,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:50:03'),(82,'ADMBD61442F','LOGIN_FAILURE',0,'hc','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-21 11:50:04'),(83,'24STUCHH010238','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-22 12:33:07'),(84,'ADMBD61442F','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-22 12:33:16'),(85,'S1024','LOGIN_SUCCESS',1,'c93a7afa-c7bc-4ea6-8dca-5ba30805d2f0','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:02:48'),(86,'S1024','LOGIN_SUCCESS',1,'5aacf2cb-fa94-4b0a-98c8-84e7842046ef','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:05:06'),(87,'S1024','LOGIN_SUCCESS',1,'5aacf2cb-fa94-4b0a-98c8-84e7842046ef','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:12:23'),(88,'S1024','LOGIN_SUCCESS',1,'57fb0b28-e26b-4e7b-8ae5-8b4fd6d4cbf2','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:14:57'),(89,'M021','LOGIN_FAILURE',0,'7356ec12-c2b8-42dc-a848-10c0ba16c889','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:18:51'),(90,'S1024','LOGIN_SUCCESS',1,'125168c4-9b66-4f2e-be1b-9f8a61a09edb','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-28 14:19:03'),(91,'S1024','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-29 08:07:31'),(92,'M021','LOGIN_FAILURE',0,'27ff24ea-329c-467f-911e-f3da2bb741e6','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:37:35'),(93,'M021','LOGIN_FAILURE',0,'31ea4b00-9b3e-4834-a6cf-fbec12fd563a','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:37:48'),(94,'S1024','LOGIN_SUCCESS',1,'9c6e8a3a-46fb-4738-bd3b-0f28cfcc8443','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:40:56'),(95,'M021','LOGIN_FAILURE',0,'9c6e8a3a-46fb-4738-bd3b-0f28cfcc8443','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:43:55'),(96,'S1024','LOGIN_FAILURE',0,'9c6e8a3a-46fb-4738-bd3b-0f28cfcc8443','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:44:04'),(97,'M021','LOGIN_SUCCESS',1,'9c6e8a3a-46fb-4738-bd3b-0f28cfcc8443','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:44:20'),(98,'ADMBD61442F','LOGIN_FAILURE',0,'9c6e8a3a-46fb-4738-bd3b-0f28cfcc8443','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:45:07'),(99,'ADMBD61442F','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:45:52'),(100,'M021','LOGIN_SUCCESS',1,'a9f91d46-bb6e-48cf-959a-3d0daeba580e','127.0.0.1','python-requests/2.34.2',NULL,NULL,'2026-10-30 12:53:39');
/*!40000 ALTER TABLE `security_events` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sis_import_reports`
--

DROP TABLE IF EXISTS `sis_import_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sis_import_reports` (
  `report_id` int NOT NULL AUTO_INCREMENT,
  `run_id` int DEFAULT NULL,
  `dry_run` tinyint(1) NOT NULL DEFAULT '1',
  `students_file` varchar(255) DEFAULT NULL,
  `mentors_file` varchar(255) DEFAULT NULL,
  `students_read` int NOT NULL DEFAULT '0',
  `mentors_read` int NOT NULL DEFAULT '0',
  `created_count` int NOT NULL DEFAULT '0',
  `updated_count` int NOT NULL DEFAULT '0',
  `skipped_count` int NOT NULL DEFAULT '0',
  `error_count` int NOT NULL DEFAULT '0',
  `warning_count` int NOT NULL DEFAULT '0',
  `report_json` json DEFAULT NULL,
  `run_by` varchar(150) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`report_id`),
  KEY `idx_import_report_run` (`run_id`),
  KEY `idx_import_report_time` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sis_import_reports`
--

LOCK TABLES `sis_import_reports` WRITE;
/*!40000 ALTER TABLE `sis_import_reports` DISABLE KEYS */;
/*!40000 ALTER TABLE `sis_import_reports` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sis_import_runs`
--

DROP TABLE IF EXISTS `sis_import_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sis_import_runs` (
  `run_id` int NOT NULL AUTO_INCREMENT,
  `started_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `finished_at` datetime DEFAULT NULL,
  `students_read` int NOT NULL DEFAULT '0',
  `students_created` int NOT NULL DEFAULT '0',
  `students_updated` int NOT NULL DEFAULT '0',
  `mentors_read` int NOT NULL DEFAULT '0',
  `mentors_created` int NOT NULL DEFAULT '0',
  `mentors_updated` int NOT NULL DEFAULT '0',
  `assignments_created` int NOT NULL DEFAULT '0',
  `assignments_updated` int NOT NULL DEFAULT '0',
  `unassigned` int NOT NULL DEFAULT '0',
  `errors_json` json DEFAULT NULL,
  `run_by` varchar(150) DEFAULT NULL,
  `report_id` int DEFAULT NULL,
  PRIMARY KEY (`run_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sis_import_runs`
--

LOCK TABLES `sis_import_runs` WRITE;
/*!40000 ALTER TABLE `sis_import_runs` DISABLE KEYS */;
INSERT INTO `sis_import_runs` VALUES (1,'2026-10-19 22:24:24','2026-10-19 22:24:24',15,15,0,2,2,0,14,0,1,'{\"errors\": [], \"warnings\": [{\"row\": 15, \"message\": \"student 24STUCHH011384: no parent_phone on file\"}]}','checkpoint3-run1',NULL),(2,'2026-10-19 22:24:24','2026-10-19 22:24:24',15,0,0,2,0,0,0,0,0,'{\"errors\": [], \"warnings\": [{\"row\": 15, \"message\": \"student 24STUCHH011384: no parent_phone on file\"}]}','checkpoint3-run2',NULL);
/*!40000 ALTER TABLE `sis_import_runs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `user_id` varchar(20) NOT NULL,
  `name` varchar(100) NOT NULL,
  `email` varchar(150) NOT NULL,
  `parent_email` varchar(150) DEFAULT NULL,
  `parent_phone` varchar(20) DEFAULT NULL,
  `phone_number` varchar(15) NOT NULL,
  `mentor_id` varchar(20) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `role` enum('student','mentor','admin') NOT NULL DEFAULT 'student',
  `password_hash` varchar(255) NOT NULL,
  `institutional_email` varchar(150) DEFAULT NULL,
  `external_id` varchar(32) DEFAULT NULL,
  `department` varchar(100) DEFAULT NULL,
  `section` varchar(20) DEFAULT NULL,
  `year` varchar(20) DEFAULT NULL,
  `account_status` enum('pending_activation','active','disabled') NOT NULL DEFAULT 'pending_activation',
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`),
  UNIQUE KEY `uq_users_institutional_email` (`institutional_email`),
  UNIQUE KEY `uq_users_external_id` (`external_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES ('24STUCHH010221','Asha Reddy','asha.reddy@student.university.edu','ramesh.reddy@example.com','9876500001','9000000001',NULL,'2026-10-19 16:54:24','student','scrypt:32768:8:1$nqXcRUbx7GK7jigl$b5ff089be09764e2160529c80546eaf491bb5f4e73867f9e3f78d3e30482b1e269b1361b412f3ed4beb4ca52e48056872a903c5c17a5076a9eff57a023e17da7','asha.reddy@student.university.edu','24STUCHH010221','Computer Science','A','1','active'),('24STUCHH010238','Bilal Ahmed','bilal.ahmed@student.university.edu','imran.ahmed@example.com','9876500002','9000000002',NULL,'2026-10-19 16:54:24','student','scrypt:32768:8:1$5wbMeiOhHmEVddSu$d52c6a460d29cdcc2c905c9744383125d5f61c620f9a066189a1b9cc7d74adbc574accd59243ea0d1a5d745f0bf94588117f7806505de935433f3789c7376632','balijepallisaisuryakarthik24@ifheindia.org','24STUCHH010238','Computer Science','A','1','active'),('24STUCHH010244','Charu Iyer','charu.iyer@student.university.edu','suresh.iyer@example.com','9876500003','9000000003',NULL,'2026-10-19 16:54:24','student','!','charu.iyer@student.university.edu','24STUCHH010244','Computer Science','B','1','pending_activation'),('24STUCHH010257','Deepak Rao','deepak.rao@student.university.edu','anil.rao@example.com','9876500004','9000000004',NULL,'2026-10-19 16:54:24','student','!','deepak.rao@student.university.edu','24STUCHH010257','Computer Science','B','1','pending_activation'),('24STUCHH010263','Esha Gupta','esha.gupta@student.university.edu','sanjay.gupta@example.com','9876500005','9000000005',NULL,'2026-10-19 16:54:24','student','!','esha.gupta@student.university.edu','24STUCHH010263','Electronics','A','1','pending_activation'),('24STUCHH010276','Farhan Ali','farhan.ali@student.university.edu','yusuf.ali@example.com','9876500006','9000000006',NULL,'2026-10-19 16:54:24','student','!','farhan.ali@student.university.edu','24STUCHH010276','Electronics','A','1','pending_activation'),('24STUCHH010282','Gita Menon','gita.menon@student.university.edu','pradeep.menon@example.com','9876500007','9000000007',NULL,'2026-10-19 16:54:24','student','!','gita.menon@student.university.edu','24STUCHH010282','Electronics','B','1','pending_activation'),('24STUCHH010295','Harish Kumar','harish.kumar@student.university.edu','vijay.kumar@example.com','9876500008','9000000008',NULL,'2026-10-19 16:54:24','student','!','harish.kumar@student.university.edu','24STUCHH010295','Electronics','B','1','pending_activation'),('24STUCHH010301','Ishita Sen','ishita.sen@student.university.edu','arun.sen@example.com','9876500009','9000000009',NULL,'2026-10-19 16:54:24','student','!','ishita.sen@student.university.edu','24STUCHH010301','Mechanical','A','1','pending_activation'),('24STUCHH010318','Jai Verma','jai.verma@student.university.edu','mohan.verma@example.com','9876500010','9000000010',NULL,'2026-10-19 16:54:24','student','!','jai.verma@student.university.edu','24STUCHH010318','Mechanical','A','1','pending_activation'),('24STUCHH010324','Kavya Pillai','kavya.pillai@student.university.edu','rajan.pillai@example.com','9876500011','9000000011',NULL,'2026-10-19 16:54:24','student','!','kavya.pillai@student.university.edu','24STUCHH010324','Mechanical','B','1','pending_activation'),('24STUCHH010337','Lokesh Nair','lokesh.nair@student.university.edu','suresh.nair@example.com','9876500012','9000000012',NULL,'2026-10-19 16:54:24','student','!','lokesh.nair@student.university.edu','24STUCHH010337','Mechanical','B','1','pending_activation'),('24STUCHH010343','Meghana Das','meghana.das@student.university.edu','gopal.das@example.com','9876500013','9000000013',NULL,'2026-10-19 16:54:24','student','!','meghana.das@student.university.edu','24STUCHH010343','Computer Science','A','1','pending_activation'),('24STUCHH011270','Omar Sheikh','omar.sheikh@student.university.edu','rashid.sheikh@example.com','9876500015','9000000015',NULL,'2026-10-19 16:54:24','student','!','omar.sheikh@student.university.edu','24STUCHH011270','Mechanical','A','1','pending_activation'),('24STUCHH011384','Nikhil Joshi','nikhil.joshi@student.university.edu','mahesh.joshi@example.com','','9000000014',NULL,'2026-10-19 16:54:24','student','!','nikhil.joshi@student.university.edu','24STUCHH011384','Electronics','B','1','pending_activation'),('ADM32430661','Administrator','bootstrap.admin@univ.edu',NULL,NULL,'',NULL,'2026-10-19 17:05:25','admin','scrypt:32768:8:1$zRuPsEUsnnGopS3f$abb973ba3e1f224ac19828d9088f34b7b1945e69072b33f17fedc0148bc5ef447a9d7146e5b7815061bac51138fb6fee29ad6932e3b190daeda59b11b37bcf01','bootstrap.admin@univ.edu','ADM32430661',NULL,NULL,NULL,'active'),('ADMBD61442F','Administrator','admin@univ.edu',NULL,NULL,'',NULL,'2026-10-20 05:24:11','admin','scrypt:32768:8:1$ne596cMuFfiJyV85$5a23ecc04262b502893c16a508e9e32eb862c9ce234771af536778f1611bc6e25d169a953f92f3d69b52965af78cb559342dd53d5b6f7788af580828825dc002','admin@univ.edu','ADMBD61442F',NULL,NULL,NULL,'active'),('M021','Harsha','harsha@univ.edu',NULL,NULL,'9000011111',NULL,'2026-09-02 12:28:29','mentor','scrypt:32768:8:1$Qck8Q2pDtYCQbGeH$930947ae82bc9f5f0cd223dd17f647c3b2598ad1b0c22a761f34a9b4365cab9627a3697ad827acf5962c8827fdabb7e3d97d242b65e666a5a64b8ad60854277b',NULL,'M021',NULL,NULL,NULL,'active'),('M045','Dr. Meera Nair','meera.nair@university.edu',NULL,NULL,'',NULL,'2026-10-19 16:54:24','mentor','!','meera.nair@university.edu','M045','Electronics',NULL,NULL,'pending_activation'),('M067','Dr. Salim Khan','salim.khan@university.edu',NULL,NULL,'',NULL,'2026-10-19 16:54:24','mentor','!','salim.khan@university.edu','M067','Mechanical',NULL,NULL,'pending_activation'),('S1024','Rahul','rahul@univ.edu','b.saisuryakarthik@gmail.com','+919063674809','7858588909','M021','2026-09-02 12:01:58','student','scrypt:32768:8:1$ACRh7CLXkbbXhcqS$46faf73fa67a8de86fba2e8ef6096741108d85bb1f358e0d6a2decd024c771be1465c89842030a75efd4ba074a31bd73247c75af3843fe536f6b2ad55dfe46f4',NULL,'S1024',NULL,NULL,NULL,'active'),('S1045','Ananya','ananya@univ.edu',NULL,NULL,'9123456780','M021','2026-09-02 12:01:58','student','placeholder',NULL,'S1045',NULL,NULL,NULL,'active'),('S2024','Priya','priya@univ.edu',NULL,NULL,'9777888999','M021','2026-09-02 16:37:34','student','scrypt:32768:8:1$EbnExSw3fAaRZLZP$d6b7d296040f4f67aee3c530f8307504dcdad6d30c24650f9bb14c13e3107cdc2691a4fceb7fd706a32767d4a7a8a7de5ade6284e2841be752b8f2dd68e9a623',NULL,'S2024',NULL,NULL,NULL,'active');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping events for database 'edushieldai'
--

--
-- Dumping routines for database 'edushieldai'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-10-31 10:24:07
